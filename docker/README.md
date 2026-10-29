# Docker 部署目录

本工程统一通过 `bash docker/docker.sh` 管理部署。从任意工作目录调用均可；命令必须明确选择 `app`、`storage` 或 `all`。分离部署和单机部署使用同一组 Compose 定义，区别是应用连接的存储 IP。

## 目录职责

```text
docker/
├── docker.sh                  # 镜像构建、启停、状态、日志及进入容器
├── Dockerfile                 # 完整源码/依赖/前端构建；上下文为工程根目录
├── Dockerfile.runtime         # 基于已核验 v0.27.2 的运行环境；不 COPY 应用源码
├── Dockerfile.{base,ci,go,deepdoc} # CI/Go/DeepDOC 的专用镜像
├── compose/                   # compose.app.yml、compose.storage.yml
├── config/                    # env.example、服务配置、Nginx、CI 后端配置
├── runtime/                   # 容器入口、源码方式启动入口
├── scripts/                   # 初始化、构建、备份、存储验证、任务与模型工具
├── manifests/                 # 镜像摘要、模型目录核验记录
├── ci/                        # CI 多后端测试矩阵；不用于 91/92 业务部署
├── env/                       # app.env / storage.env，权限 600，不提交
├── state/                     # 生成的 service_conf.yaml，不提交
├── logs/                      # 应用日志，不提交
├── backups/                   # 私有备份，不提交
└── evidence/                  # 排查证据，不提交
```

`ci/` 保留的 Go/Python、Infinity、OceanBase 等文件由 `.github/workflows/sep-tests.yml` 实际使用。无消费者的 macOS、OC9 Compose、OC9/TEI Dockerfile、旧迁移入口和单桶示例已删除。原 `split/` 不再作为部署入口。

## 挂载方式

宿主机工程根目录整体绑定到 `/ragflow`，API、Worker、解析代码和模型目录直接来自当前 checkout。进入容器后修改工程会同步到宿主机。Python 修改后执行 `restart app` 重新加载，无需打补丁镜像。

整目录挂载会遮住镜像内 `/ragflow`，因此 `.venv`、DeepDOC 模型、预编译前端和 `bin` 使用按镜像 ID 区分的只读 Docker 卷，由 Docker 在首次创建时从镜像填充；镜像改变时自动使用新的卷。Tika、tokenizer 缓存和版本文件由镜像中的 `/opt/ragflow-runtime` 提供，不包含应用源码。生成的服务配置单独绑定到 `state/`，不会覆盖工程原有的 `conf/service_conf.yaml`。

前端改动需在宿主机执行 `cd web && npm ci && npm run build`，再将 `app.env` 的 `APP_WEB_DIST` 设为该主机工程 `web/dist` 的绝对路径，执行 `recreate app`。未配置时使用与运行镜像配套的预编译前端。Python 依赖/原生库变化需构建完整镜像，修改 `RAGFLOW_IMAGE` 后重建；不要在只读依赖卷内安装包。

## 新环境初始化

```bash
# 只在首次部署时生成；文件存在则拒绝覆盖。
bash docker/docker.sh init --app-ip 192.168.88.91 --storage-ip 192.168.88.92 --app-memory 48g
# 单机使用相同 IP；例如两项均为 192.168.88.92，--app-memory 6g。
```

分离部署将 `env/app.env` 安全传到应用主机，将匹配的 `env/storage.env` 传到存储主机。已有部署沿用原密码，不能重新生成。默认应用端口 8088/9380/9381，可通过 `APP_WEB_PORT`、`APP_API_PORT`、`APP_ADMIN_PORT` 调整。存储绑定 `STORAGE_IP`，不是容器内的 127.0.0.1。

## 常用命令

```bash
bash docker/docker.sh help
bash docker/docker.sh build runtime ragflow-local:v0.27.2-runtime-20261029
# 在 env/app.env 设置 RAGFLOW_IMAGE 为上面的镜像标签。
bash docker/docker.sh config app
bash docker/docker.sh start storage       # 分离部署在 92
bash docker/docker.sh start app           # 分离部署在 91
bash docker/docker.sh start all           # 单机在 92：先存储、后应用
bash docker/docker.sh status all
bash docker/docker.sh logs app --tail 100
bash docker/docker.sh into app            # 进入 /ragflow 的 Bash
bash docker/docker.sh into storage mysql  # 进入 MySQL 容器的 sh
bash docker/docker.sh restart app
bash docker/docker.sh recreate app        # 镜像、挂载或 env 变化后使用
bash docker/docker.sh stop all            # 先应用、后存储
bash docker/docker.sh down app            # 移除该项目应用容器/网络；保留数据卷
```

`start`/`recreate` 等待健康并禁止隐式拉取；首次安装缺少基础镜像时先显式 `docker pull infiniflow/ragflow:v0.27.2`，存储镜像使用 `pull storage`。`build source TAG [docker build 参数]` 使用完整 Dockerfile，需要依赖镜像及构建网络。`exec ROLE SERVICE COMMAND...` 为自动化提供非交互入口，人工操作使用 `into` 后执行原生命令。

项目名固定为 `ragflow-app` 和 `ragflow-storage`，环境中的 `COMPOSE_PROJECT_NAME`、`COMPOSE_FILE` 和 `COMPOSE_PROFILES` 不会改变目标。入口不接受 `down -v`、全局 prune 或任意 Compose 参数。91 的旧实例属于项目 `docker`，禁止对其存储容器操作。

完整部署、容器内操作、备份、恢复及现场验证见 [operations.html](../docs/operations.html)。精炼工作日志见 [update.md](../docs/update.md)。
