#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
target=${1:-}
case "$target" in
  app|storage) shift ;;
  *) echo "Usage: bash ops.sh {app|storage} <docker compose arguments>" >&2; exit 2 ;;
esac
test -f "$target.env" || { echo "Missing $target.env; see docs/install.md" >&2; exit 1; }
exec docker compose --env-file "$target.env" -f "compose.$target.yml" "$@"
