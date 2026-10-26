#!/usr/bin/env bash
# A consistent backup requires all application writers to have stopped on 91.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ${APP_STOPPED:-0} != 1 ]]; then
  echo "Stop the new app on 91, then run APP_STOPPED=1 bash backup.sh on 92." >&2
  exit 2
fi
if curl -fsS --connect-timeout 3 --max-time 5 "http://${APP_IP:-192.168.88.91}:9380/api/v1/system/ping" >/dev/null 2>&1; then
  echo "The application is still serving requests; refusing an inconsistent backup." >&2
  exit 1
fi
umask 077
set -a
source <(sed 's/\r$//' storage.env)
set +a
backup_dir="$(pwd)/backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
bash ops.sh storage stop
trap 'bash ops.sh storage up -d --pull never --wait --wait-timeout 240' EXIT
for name in mysql_data es_data es_snapshots minio_data redis_data kibana_data redisinsight_data; do
  volume="ragflow-storage_$name"
  test "$(docker volume inspect -f '{{index .Labels "com.docker.compose.project"}}' "$volume")" = ragflow-storage
  docker run --rm --network none --entrypoint tar \
    --mount "type=volume,source=$volume,target=/source,readonly" \
    --mount "type=bind,source=$backup_dir,target=/backup" \
    "$MYSQL_IMAGE" --numeric-owner -czf "/backup/$name.tar.gz" -C /source .
done
cp -- storage.env compose.storage.yml "$backup_dir/"
for archive in "$backup_dir"/*.tar.gz; do
  gzip -t "$archive"
done
(cd "$backup_dir" && sha256sum ./*.tar.gz > SHA256SUMS)
echo "Backup complete: $backup_dir"
echo "Save app.env and the deployed source revision from 91 in the same backup set. Restart the app after storage is healthy."
