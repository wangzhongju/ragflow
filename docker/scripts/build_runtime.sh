#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
tag=${1:-ragflow-local:v0.27.2-runtime}
[[ $tag == ragflow-local:* ]] || { echo 'Use a dedicated ragflow-local tag.' >&2; exit 2; }
base=infiniflow/ragflow:v0.27.2
expected=sha256:e0e1d9ec4af666710a35f3f7e1e3fe6b450b6a2cfe52851f107fc5f5967bbe8f
[[ $(docker image inspect -f '{{.Id}}' "$base") == "$expected" ]] || { echo 'Base image digest mismatch.' >&2; exit 1; }
# No application source, credentials or runtime data enter this build context.
tar -cf - docker/Dockerfile.runtime | \
  DOCKER_BUILDKIT=0 docker build --network none --pull=false -f docker/Dockerfile.runtime -t "$tag" -
python3 - "$tag" "$base" "$expected" <<'PY'
import json, socket, subprocess, sys
from pathlib import Path
manifest = {
    "image": sys.argv[1],
    "config_digest": subprocess.check_output(["docker", "image", "inspect", "-f", "{{.Id}}", sys.argv[1]], text=True).strip(),
    "base_image": sys.argv[2],
    "base_config_digest": sys.argv[3],
    "build_host": socket.gethostname(),
    "application_source": "host checkout bind-mounted at /ragflow",
}
Path("docker/manifests/runtime-image.lock.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(json.dumps(manifest, indent=2))
PY
