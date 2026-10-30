#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$DIR/.." && pwd)"
export RAGFLOW_ENV_DIR="${RAGFLOW_ENV_DIR:-$DIR/env}"
[[ $RAGFLOW_ENV_DIR = /* ]] || RAGFLOW_ENV_DIR="$PWD/$RAGFLOW_ENV_DIR"

die() { echo "$*" >&2; exit 2; }
help() {
  cat <<'EOF'
Usage: docker/docker.sh COMMAND ROLE [ARGS]

  init --app-ip IP --storage-ip IP [--app-memory 8g]
                              Generate matching env files once; never overwrite.
  build runtime [TAG]         Build the pinned runtime image (source is mounted).
  build source TAG [ARGS]     Build docker/Dockerfile from the repository root.
  pull app|storage            Download the configured images explicitly.
  start app|storage|all       Start and wait for health (no implicit pull).
  recreate app|storage|all    Recreate containers and wait; retain volumes.
  stop app|storage|all        Stop containers; all stops app first.
  restart app|storage|all     Restart services and wait for health.
  down app|storage|all        Remove project containers/network; retain volumes.
  status app|storage|all      List containers, including stopped ones.
  config app|storage|all      Validate configuration without printing secrets.
  logs app|storage [ARGS]     Compose logs arguments, e.g. --tail 100 mysql.
  into app                   Open Bash as the calling host user, with sudo.
  into storage SERVICE       Open sh in mysql/redis/minio/elasticsearch/etc.
  exec app|storage SERVICE COMMAND [ARGS]
                              Non-interactive command for scripts/redirects.
  help                       Show this help.

Split: storage commands on the storage host, app commands on the app host.
Single host: use all; app connects to that host's published storage IP.
Projects are fixed to ragflow-app / ragflow-storage. No volume deletion.
RAGFLOW_ENV_DIR selects an absolute env directory (default docker/env).
EOF
}

compose() {
  local role=$1; shift
  # Explicit project, env and project directory prevent caller-directory drift.
  env -u COMPOSE_PROFILES -u COMPOSE_FILE -u COMPOSE_PROJECT_NAME \
    docker compose --project-directory "$DIR/compose" \
    --env-file "$RAGFLOW_ENV_DIR/$role.env" --project-name "ragflow-$role" \
    -f "$DIR/compose/compose.$role.yml" "$@"
}

validate() {
  local role=$1
  [[ -f "$RAGFLOW_ENV_DIR/$role.env" ]] || die "Missing $RAGFLOW_ENV_DIR/$role.env; see docker/README.md."
  compose "$role" config --quiet
}

start() {
  local role=$1; shift
  if [[ $role == storage ]]; then
    compose storage up -d --pull never --wait --wait-timeout 300 "$@" mysql redis minio elasticsearch
    compose storage exec -T --user root elasticsearch sh /opt/ragflow-ops/configure_storage.sh
    compose storage up -d --pull never --wait --wait-timeout 300 "$@" kibana redisinsight
  else
    local image image_id
    image=$(compose app config --images)
    image_id=$(docker image inspect -f '{{.Id}}' "$image")
    [[ $image_id =~ ^sha256:[a-f0-9]{64}$ ]] || die 'Cannot resolve application image ID'
    export RAGFLOW_RUNTIME_KEY=${image_id#sha256:}
    mkdir -p "$DIR/state" "$DIR/home"
    chmod 700 "$DIR/state"
    touch "$DIR/state/service_conf.yaml"
    chmod 600 "$DIR/state/service_conf.yaml"
    if [[ $(id -u) == 0 ]]; then
      chown "$DOCKER_USER_ID:$DOCKER_GRP_ID" "$DIR/state" "$DIR/state/service_conf.yaml" "$DIR/home"
    fi
    compose app up -d --pull never --wait --wait-timeout 480 "$@"
  fi
}

action=${1:-help}
shift || true
case "$action" in
  help|-h|--help) help; exit ;;
  init) exec python3 "$DIR/scripts/init_env.py" "$@" ;;
  build)
    kind=${1:-}; [[ $# -gt 0 ]] && shift
    case "$kind" in
      runtime) [[ $# -le 1 ]] || die 'build runtime accepts one tag'; exec bash "$DIR/scripts/build_runtime.sh" "$@" ;;
      source)
        [[ $# -ge 1 ]] || die 'build source requires an image tag'
        tag=$1; shift
        exec docker build -f "$DIR/Dockerfile" -t "$tag" "$@" "$ROOT" ;;
      *) die 'Use build runtime [TAG] or build source TAG [docker build arguments]' ;;
    esac ;;
  start|recreate|stop|restart|down|status|config|pull|logs|into|exec) ;;
  *) die "Unknown command: $action (see help)" ;;
esac

role=${1:-}
case "$role" in app|storage|all) shift ;; *) die 'Specify role: app, storage or all' ;; esac
if [[ $role == app || $role == all ]]; then
  export DOCKER_USER=${SUDO_USER:-$(id -un)}
  export DOCKER_USER_ID=$(id -u "$DOCKER_USER")
  export DOCKER_GRP=$(id -gn "$DOCKER_USER")
  export DOCKER_GRP_ID=$(id -g "$DOCKER_USER")
  [[ $DOCKER_USER_ID -gt 0 ]] || die 'Run app commands as the non-root host user (or via sudo from that user)'
fi
case "$action" in
  start|recreate|stop|restart|down|status|config|pull) [[ $# == 0 ]] || die "$action accepts no extra arguments" ;;
esac
roles=("$role")
if [[ $role == all ]]; then
  case "$action" in into|exec|logs|pull) die "$action requires app or storage" ;; esac
  roles=(storage app)
  case "$action" in stop|down) roles=(app storage) ;; esac
fi
# Validate every selected role before making the first change.
for selected in "${roles[@]}"; do validate "$selected"; done
if [[ $role == all && ( $action == restart || $action == recreate ) ]]; then
  compose app stop
fi

for selected in "${roles[@]}"; do
  case "$action" in
    start) start "$selected" ;;
    recreate) start "$selected" --force-recreate ;;
    restart) compose "$selected" restart; start "$selected" ;;
    stop|down|pull) compose "$selected" "$action" ;;
    status) compose "$selected" ps -a ;;
    config) echo "ragflow-$selected: configuration valid" ;;
    logs) compose "$selected" logs "$@" ;;
    into)
      service=${1:-}; shell=sh
      if [[ $selected == app ]]; then service=${service:-ragflow}; shell=bash; fi
      [[ -n $service && $# -le 1 ]] || die 'into storage requires exactly one service'
      if [[ $selected == app ]]; then
        [[ $service == ragflow ]] || die 'The app service is ragflow'
        compose app exec -T --user root \
          -e "DOCKER_USER=$DOCKER_USER" -e "DOCKER_USER_ID=$DOCKER_USER_ID" \
          -e "DOCKER_GRP=$DOCKER_GRP" -e "DOCKER_GRP_ID=$DOCKER_GRP_ID" \
          ragflow bash /ragflow/docker/runtime/env.sh
        compose app exec --user "$DOCKER_USER_ID:$DOCKER_GRP_ID" \
          -e "HOME=/home/$DOCKER_USER" -e "USER=$DOCKER_USER" -e "LOGNAME=$DOCKER_USER" \
          --workdir /ragflow ragflow bash --login
      else
        compose "$selected" exec "$service" "$shell"
      fi ;;
    exec)
      [[ $# -ge 2 && $1 != -* ]] || die 'exec requires SERVICE COMMAND [ARGS]'
      compose "$selected" exec -T "$@" ;;
  esac
done
