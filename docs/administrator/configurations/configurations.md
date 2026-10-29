---
sidebar_position: 0
slug: /configurations
sidebar_custom_props: {
  categoryIcon: LucideCog
}
---
# Configuration

This checkout uses `docker/env/app.env` and `docker/env/storage.env`, generated once by `docker/docker.sh init`. See the [deployment directory](../../../docker/README.md) and [operations manual](../../operations.html). Existing deployments retain their original passwords.

| Configuration | Purpose |
| --- | --- |
| `APP_IP`, `APP_WEB_PORT`, `APP_API_PORT`, `APP_ADMIN_PORT` | Application bind address and published ports; defaults 8088/9380/9381. |
| `APP_MEM_LIMIT`, `APP_MEM_RESERVATION` | Per-host application memory settings. |
| `RAGFLOW_IMAGE` | Runtime image built with `Dockerfile.runtime`, or full image built with `Dockerfile`. |
| `APP_WEB_DIST` | Optional absolute path to host-built `web/dist`; otherwise image frontend assets are used. |
| `STORAGE_IP` | Storage host bind address. |
| `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_DBNAME`, `MYSQL_PASSWORD` | Application metadata connection. |
| `ES_HOST`, `ELASTIC_PASSWORD` | Elasticsearch connection. |
| `MINIO_HOST`, `MINIO_USER`, `MINIO_PASSWORD` | Object storage connection. |
| `REDIS_HOST`, `REDIS_PASSWORD` | Redis connection; business data uses DB 1. |
| `KIBANA_PASSWORD`, `KIBANA_ENCRYPTION_KEY` | Kibana service credentials and encryption. |
| `MYSQL_IMAGE`, `ES_IMAGE`, `MINIO_IMAGE`, `REDIS_IMAGE` | Storage images; verify digests before upgrades. |

The mounted `docker/config/service_conf.yaml.template` is rendered into `docker/state/service_conf.yaml`. The checkout's `conf/service_conf.yaml` is not overwritten. The whole checkout is mounted at `/ragflow`; runtime dependencies are separate image-keyed volumes.

```bash
bash docker/docker.sh config app
bash docker/docker.sh config storage
# After changing env, image, or mount configuration:
bash docker/docker.sh recreate app
```

The CI backend matrix uses `docker/ci/env.example` and `docker/config/service_conf.ci.yaml.template`. Those profiles are for automated backend tests and are not the deployment configuration of the 91/92 servers.
