"""Create both hosts' matching configuration files once; never overwrite secrets."""

import os
from pathlib import Path
import secrets


def main():
    root = Path(__file__).parent
    targets = [root / "app.env", root / "storage.env"]
    if any(target.exists() for target in targets):
        raise SystemExit("app.env or storage.env already exists; refusing to regenerate credentials.")
    values = dict(line.split("=", 1) for line in (root / "env.example").read_text().splitlines() if line and not line.startswith("#"))
    for key, value in values.items():
        if value.startswith("REPLACE_"):
            values[key] = secrets.token_hex(24)
    app_keys = {
        "APP_IP", "APP_WEB_PORT", "RAGFLOW_IMAGE", "MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_DBNAME",
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
