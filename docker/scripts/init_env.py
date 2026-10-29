"""Create both hosts' matching configuration files once; never overwrite secrets."""

import argparse
import ipaddress
import os
from pathlib import Path
import secrets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-ip", required=True)
    parser.add_argument("--storage-ip", required=True)
    parser.add_argument("--app-memory", default="8g")
    args = parser.parse_args()
    for address in (args.app_ip, args.storage_ip):
        if ipaddress.ip_address(address).is_unspecified:
            parser.error("Use a reachable host IP, not an unspecified bind address")
    import re
    if not re.fullmatch(r"[1-9][0-9]*[gm]", args.app_memory):
        parser.error("--app-memory must look like 8g or 4096m")
    docker_dir = Path(__file__).resolve().parents[1]
    root = Path(os.environ.get("RAGFLOW_ENV_DIR", docker_dir / "env"))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    targets = [root / "app.env", root / "storage.env"]
    if any(target.exists() for target in targets):
        raise SystemExit("app.env or storage.env already exists; refusing to regenerate credentials.")
    values = dict(line.split("=", 1) for line in (docker_dir / "config/env.example").read_text().splitlines() if line and not line.startswith("#"))
    for key, value in values.items():
        if value.startswith("REPLACE_"):
            values[key] = secrets.token_hex(24)
    values.update(APP_IP=args.app_ip, STORAGE_IP=args.storage_ip, APP_MEM_LIMIT=args.app_memory)
    for key in ("MYSQL_HOST", "MINIO_HOST", "ES_HOST", "REDIS_HOST"):
        values[key] = args.storage_ip
    app_keys = {
        "APP_IP", "APP_WEB_PORT", "APP_API_PORT", "APP_ADMIN_PORT", "APP_MEM_LIMIT", "APP_MEM_RESERVATION", "RAGFLOW_IMAGE", "MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_DBNAME",
        "MYSQL_MAX_PACKET", "MYSQL_PASSWORD", "MINIO_HOST", "MINIO_USER", "MINIO_PASSWORD", "ES_HOST",
        "ELASTIC_PASSWORD", "REDIS_HOST", "REDIS_PASSWORD", "DOC_ENGINE", "DB_TYPE", "STORAGE_IMPL",
        "API_PROXY_SCHEME", "TZ", "REGISTER_ENABLED", "ENABLE_REGISTER", "ADMIN_DEFAULT_PASSWORD", "RAGFLOW_SECRET_KEY", "USE_DOCLING",
    }
    storage_keys = {
        "STORAGE_IP", "MYSQL_IMAGE", "ES_IMAGE", "KIBANA_IMAGE", "MINIO_IMAGE", "REDIS_IMAGE", "REDISINSIGHT_IMAGE",
        "MYSQL_ROOT_PASSWORD", "MYSQL_PASSWORD", "ELASTIC_PASSWORD", "MINIO_USER", "MINIO_PASSWORD", "REDIS_PASSWORD",
        "KIBANA_PASSWORD", "KIBANA_ENCRYPTION_KEY", "REDISINSIGHT_ENCRYPTION_KEY",
    }
    for path, keys in zip(targets, [app_keys, storage_keys]):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.writelines(f"{key}={value}\n" for key, value in values.items() if key in keys)
        print(f"Created {path.name}; transfer only to its intended host.")


if __name__ == "__main__":
    main()
