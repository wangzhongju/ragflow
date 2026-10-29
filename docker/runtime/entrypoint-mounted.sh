#!/usr/bin/env bash
set -euo pipefail
cd /ragflow
# These are image dependencies, not application source. Python, models and the
# prebuilt frontend use image-keyed volumes; the entire checkout is a bind mount.
for asset in VERSION 9b5ad71b2ce5302211f9c61530b329a4922fc6a4 \
  tika-server-standard-3.3.0.jar tika-server-standard-3.3.0.jar.md5; do
  if ! cmp -s "/opt/ragflow-runtime/$asset" "/ragflow/$asset"; then
    cp -- "/opt/ragflow-runtime/$asset" "/ragflow/$asset"
  fi
done
exec bash /ragflow/docker/runtime/entrypoint.sh "$@"
