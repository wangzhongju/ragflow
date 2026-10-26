#!/usr/bin/env bash
# Build only the reviewed Python patch on the verified release image.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
patch_tag=${1:-ragflow-local:v0.27.2-progress-20261023}
[[ $patch_tag == ragflow-local:* ]] || { echo "Use a dedicated ragflow-local tag." >&2; exit 2; }
base_image=infiniflow/ragflow:v0.27.2
expected_base=sha256:e0e1d9ec4af666710a35f3f7e1e3fe6b450b6a2cfe52851f107fc5f5967bbe8f
[[ $(docker image inspect -f '{{.Id}}' "$base_image") == "$expected_base" ]] || { echo "Base image digest mismatch." >&2; exit 1; }
files=(api/db/__init__.py api/db/services/pipeline_operation_log_service.py rag/flow/pipeline.py rag/svr/task_executor.py deepdoc/parser/pdf_parser.py)
# Explicit file list keeps credentials, logs and database backups out of context.
tar -cf - docker/split/Dockerfile.patch "${files[@]}" |
  DOCKER_BUILDKIT=0 docker build --network none --pull=false -f docker/split/Dockerfile.patch -t "$patch_tag" -
docker run --rm --network none --entrypoint python "$patch_tag" -m compileall -q "${files[@]}"
python3 - "$patch_tag" "$base_image" "$expected_base" "${files[@]}" <<'PY'
import hashlib, json, subprocess, sys
from pathlib import Path
manifest = {
    "image": sys.argv[1],
    "config_digest": subprocess.check_output(["docker", "image", "inspect", "-f", "{{.Id}}", sys.argv[1]], text=True).strip(),
    "base_image": sys.argv[2],
    "base_config_digest": sys.argv[3],
    "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "patched_files_sha256": {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in sys.argv[4:]},
}
Path("docker/split/patch-image.lock.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(json.dumps(manifest, indent=2))
PY