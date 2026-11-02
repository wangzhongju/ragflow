#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ ${1:-} == fetch && ${2:-} == --check ]]; then
  shift
  exec python3 "$ROOT/docker/scripts/fetch_artifacts.py" "$@"
fi
config="${RAGFLOW_ENV_DIR:-$ROOT/docker/env}/build.env"
SSH_TUNNEL_ENABLED=${SSH_TUNNEL_ENABLED:-0}
SSH_TUNNEL_PROXY=${SSH_TUNNEL_PROXY:-http://127.0.0.1:17897}
if [[ -f $config ]]; then
  # This private file is shell configuration, owned by the build-host user.
  source "$config"
fi
build_network=default
proxy_args=()
case $SSH_TUNNEL_ENABLED in
  0) ;;
  1)
    [[ $SSH_TUNNEL_PROXY =~ ^http://127\.0\.0\.1:[0-9]+$ ]] || {
      echo 'SSH_TUNNEL_PROXY must be http://127.0.0.1:PORT' >&2; exit 2;
    }
    export http_proxy="$SSH_TUNNEL_PROXY" https_proxy="$SSH_TUNNEL_PROXY"
    export HTTP_PROXY="$SSH_TUNNEL_PROXY" HTTPS_PROXY="$SSH_TUNNEL_PROXY"
    export no_proxy=localhost,127.0.0.1 NO_PROXY=localhost,127.0.0.1
    build_network=host
    for name in http_proxy https_proxy HTTP_PROXY HTTPS_PROXY no_proxy NO_PROXY; do
      proxy_args+=(--build-arg "$name=${!name}")
    done
    python3 - "$SSH_TUNNEL_PROXY" <<'PY'
import socket, sys
from urllib.parse import urlsplit
address = urlsplit(sys.argv[1])
try:
    socket.create_connection((address.hostname, address.port), timeout=3).close()
except OSError as error:
    raise SystemExit(f'SSH tunnel is unavailable: {error}. Start the local ssh -R command in docker/config/build.env.example.')
PY
    ;;
  *) echo 'SSH_TUNNEL_ENABLED must be 0 or 1' >&2; exit 2 ;;
esac
action=${1:?Specify fetch, dev or prod}; shift
case $action in
  fetch) exec python3 "$ROOT/docker/scripts/fetch_artifacts.py" "$@" ;;
  dev|prod) ;;
  *) echo 'Specify fetch, dev or prod' >&2; exit 2 ;;
esac
[[ $# -ge 1 && -n $1 ]] || { echo 'build requires an image tag' >&2; exit 2; }
tag=$1; shift
[[ $(uname -m) == x86_64 ]] || { echo 'These browser-enabled images require Linux amd64.' >&2; exit 2; }
python3 "$ROOT/docker/scripts/fetch_artifacts.py"
file="$ROOT/docker/Dockerfile"
[[ $action != dev ]] || file+=.dev
exec docker build --network "$build_network" "${proxy_args[@]}" -f "$file" -t "$tag" "$@" "$ROOT"
