#!/usr/bin/env bash
# All app writers, including apps on other hosts, must be stopped first.
set -euo pipefail
DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="${RAGFLOW_ENV_DIR:-$DIR/env}"
[[ ${APP_STOPPED:-0} == 1 && -n ${APP_URLS:-} ]] || {
  echo 'Stop every app writer; set APP_STOPPED=1 and APP_URLS to every app API URL.' >&2
  exit 2
}
for url in $APP_URLS; do
  if curl -sS --connect-timeout 3 --max-time 5 "$url/api/v1/system/ping" >/dev/null 2>&1; then
    echo "Application still responds at $url; refusing backup." >&2
    exit 1
  fi
done
bash "$DIR/docker.sh" config storage
volumes=(mysql_data es_data es_snapshots minio_data redis_data kibana_data redisinsight_data)
for name in "${volumes[@]}"; do
  [[ $(docker volume inspect -f '{{index .Labels "com.docker.compose.project"}}' "ragflow-storage_$name") == ragflow-storage ]]
done
running_ids=$(docker ps -q --filter label=com.docker.compose.project=ragflow-storage)
running=()
if [[ -n $running_ids ]]; then mapfile -t running <<< "$running_ids"; fi
image=$(docker inspect -f '{{.Config.Image}}' ragflow-storage-mysql-1)
umask 077
backup_dir="$DIR/backups/$(date +%Y%m%d-%H%M%S)"
mkdir -m 700 "$backup_dir"
restore() {
  if [[ ${#running[@]} -gt 0 ]]; then docker start "${running[@]}" >/dev/null; fi
}
trap restore EXIT
bash "$DIR/docker.sh" stop storage
for name in "${volumes[@]}"; do
  docker run --rm --network none --entrypoint tar \
    --mount "type=volume,source=ragflow-storage_$name,target=/source,readonly" \
    --mount "type=bind,source=$backup_dir,target=/backup" \
    "$image" --numeric-owner -czf "/backup/$name.tar.gz" -C /source .
done
cp -- "$ENV_DIR/storage.env" "$DIR/compose/compose.storage.yml" "$backup_dir/"
for archive in "$backup_dir"/*.tar.gz; do gzip -t "$archive"; done
(cd "$backup_dir" && sha256sum ./*.tar.gz > SHA256SUMS)
echo "Backup complete: $backup_dir"
echo 'Previously running storage containers will be restarted. Verify health before restarting every app.'
