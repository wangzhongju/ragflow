# Docker 部署目录

本工程统一通过 `bash docker/docker.sh` 管理部署。从任意工作目录调用均可；命令必须明确选择 `app`、`storage` 或 `all`。分离部署和单机部署使用同一组 Compose 定义，区别是应用连接的存储 IP。

## 工程结构索引

本目录及全工程的递归文件职责统一见 [完整工程文件职责索引](../docs/project-structure.html#docker)，这里维护部署命令与配置用法。

## 挂载方式

宿主机工程根目录整体绑定到 `/ragflow`，API、Worker、解析代码和模型目录直接来自当前 checkout。进入容器后修改工程会同步到宿主机。Python 修改后执行 `restart app` 重新加载，无需打补丁镜像。

整目录挂载会遮住镜像内 `/ragflow`，因此 `.venv`、DeepDOC 模型、预编译前端和 `bin` 使用按镜像 ID 区分的只读 Docker 卷，由 Docker 在首次创建时从镜像填充；镜像改变时自动使用新的卷。Tika、tokenizer 缓存和版本文件由镜像中的 `/opt/ragflow-runtime` 提供，不包含应用源码。生成的服务配置单独绑定到 `state/`，不会覆盖工程原有的 `conf/service_conf.yaml`。

前端改动需在宿主机执行 `cd web && npm ci && npm run build`，再将 `app.env` 的 `APP_WEB_DIST` 设为该主机工程 `web/dist` 的绝对路径，执行 `recreate app`。未配置时使用与运行镜像配套的预编译前端。Python 依赖/原生库变化需构建完整镜像，修改 `RAGFLOW_IMAGE` 后重建；不要在只读依赖卷内安装包。

## 应用容器用户与工具

使用普通宿主机用户运行入口（通过该用户 sudo 调用也能识别原用户）。`docker.sh` 读取用户名、主组及 UID/GID，应用启动和 `into app` 时由 `runtime/env.sh` 建立一致账户；若 UID 1000 已由基础镜像 ubuntu 占用，复用该 UID 并调整账号名。系统账户或同名不同 ID 会报错，不递归修改工程所有权。

`into app` 进入该用户的登录 Bash，支持免密 sudo、vim、bash-completion、less、git、curl、wget、unzip、ps、ip、ping。首次从 `/etc/skel` 建立完整个人 `.bashrc`、`.profile`，PS1 与 91 的 vision-pipeline 一致（绿用户名、紫主机名、青路径）；工程环境放在个人 `.ragflow_env`。文件存在后不重写，用户可自由修改。Python 及 NLTK 可由普通用户访问，`docker/home` 持久保存环境文件和历史。后台服务继续沿用现有启动身份；存储容器保持镜像原生账户，不添加这些开发工具。

镜像保留 apt 软件包索引，进入后可直接 `sudo apt-get install cmake`，也可正常 `sudo apt-get update`。容器内安装的系统包在重建后丢失，长期依赖请加入 Dockerfile；个人环境文件会保留。

镜像新增系统工具需要 apt 网络；国内网络可用 `NEED_MIRROR=1 BUILD_NETWORK=host bash docker/docker.sh build runtime TAG`。Python 依赖卷只读，依赖变化应构建镜像，不能在进入容器后直接向只读卷 pip 安装。

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
bash docker/docker.sh build runtime ragflow-local:v0.27.2-dev-20261029
# 在 env/app.env 设置 RAGFLOW_IMAGE 为上面的镜像标签。
bash docker/docker.sh config app
bash docker/docker.sh start storage       # 分离部署在 92
bash docker/docker.sh start app           # 分离部署在 91
bash docker/docker.sh start all           # 单机在 92：先存储、后应用
bash docker/docker.sh status all
bash docker/docker.sh logs app --tail 100
bash docker/docker.sh into app            # 以宿主机用户进入 /ragflow，支持 sudo
bash docker/docker.sh into storage mysql  # 进入 MySQL 容器的 sh
bash docker/docker.sh restart app
bash docker/docker.sh recreate app        # 镜像、挂载或 env 变化后使用
bash docker/docker.sh stop all            # 先应用、后存储
bash docker/docker.sh down app            # 移除该项目应用容器/网络；保留数据卷
```

`start`/`recreate` 等待健康并禁止隐式拉取；首次安装缺少基础镜像时先显式 `docker pull infiniflow/ragflow:v0.27.2`，存储镜像使用 `pull storage`。`exec ROLE SERVICE COMMAND...` 为自动化提供非交互入口，人工操作使用 `into` 后执行原生命令。

## 完整源码镜像构建

```bash
bash docker/docker.sh build source ragflow-local:my-release --build-arg NEED_MIRROR=1
```

`Dockerfile` 和 `Dockerfile.base` 的 `DEPS_IMAGE` 默认固定为 `infiniflow/ragflow_deps:latest-python@sha256:e69762c256ea2338a786a9b2f003da8e91e5e69b26bb6797c2206276ce32e5ff`。Chrome/ChromeDriver、Tika、uv、Stagehand、NLTK 和模型来自该镜像；无需放进宿主机工程根目录。上游 `latest` 已变成 Go 依赖包，缺少 Python 构建所需文件，不能用它替换固定版本。

`NEED_MIRROR=1` 切换 Dockerfile 中配置的软件源，构建仍需访问镜像仓库及 GitHub 等下载服务。自行制作完整 Python 依赖镜像时，通过 `--build-arg DEPS_IMAGE=镜像名:标签` 指定；步骤与排障见 [操作手册 3.4](../docs/operations.html#source-build)。

项目名固定为 `ragflow-app` 和 `ragflow-storage`，环境中的 `COMPOSE_PROJECT_NAME`、`COMPOSE_FILE` 和 `COMPOSE_PROFILES` 不会改变目标。入口不接受 `down -v`、全局 prune 或任意 Compose 参数。91 的旧实例属于项目 `docker`，禁止对其存储容器操作。

完整部署、容器内操作、备份、恢复及现场验证见 [operations.html](../docs/operations.html)。精炼工作日志见 [update.md](../docs/update.md)。
