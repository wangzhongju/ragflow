# Docker 部署

统一入口为 `bash docker/docker.sh`，角色必须明确选择 `app`、`storage` 或 `all`。分离与同机部署共用 Compose，区别是存储 IP。

## 构建与切换模式

```bash
# 官方资源缓存到工程根 third_partys；完整文件跳过下载。
bash docker/docker.sh fetch
bash docker/docker.sh fetch --check  # 离线核验，不下载
bash docker/docker.sh build dev ragflow-local:dev
bash docker/docker.sh build prod ragflow-local:prod
```

应用仅使用 `Dockerfile.dev` 和 `Dockerfile`，分别启动 Vite 开发前端、编译并提供生产前端。二者从 Ubuntu 和本地资源构建，不使用外部 RAGFlow 依赖镜像。构建需要 Linux amd64、Docker BuildKit、Python 3.10+。apt、uv、npm 的首次安装仍需联网，资源缓存不等于完整离线构建。

修改 `docker/env/app.env` 后执行 `bash docker/docker.sh recreate app`：

| 主机/用途 | APP_MODE | RAGFLOW_IMAGE |
|---|---|---|
| 91 开发 | dev | ragflow-local:dev-20261030 |
| 92 生产 | prod | ragflow-local:prod-20261030 |

新环境使用自己构建的标签。入口核验镜像模式，不匹配时拒绝启动。构建不切换应用，也不修改镜像记录文件。

## 可选 SSH 下载隧道

假设本地 Windows 已有 HTTP 代理 `127.0.0.1:7897`，在本地终端执行并保持连接：

```powershell
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -R 127.0.0.1:17897:127.0.0.1:7897 cdky@192.168.88.91
```

91 首次复制 `docker/config/build.env.example` 为 `docker/env/build.env`，设置 `SSH_TUNNEL_ENABLED=1`、`SSH_TUNNEL_PROXY=http://127.0.0.1:17897`，再执行 fetch/build。代理端口按本地配置调整。脚本向下载进程和 Docker 标准 HTTP(S)_PROXY 构建参数传递代理，构建网络使用 host。隧道仅监听服务器回环地址，不写入镜像运行环境。完成后关闭本地 SSH，恢复 `SSH_TUNNEL_ENABLED=0`；无代理时保持 0。

清单固定官方 URL、版本/提交、大小和 SHA-256。模型、NLTK、Tika、tiktoken、Chrome/Driver 等均缓存到 `third_partys`；校验失败重下，下载中断不替换原文件。NLTK 解压结果也会校验，缺失时从本地 ZIP 恢复。缓存被 Git 忽略，新环境执行 fetch 即可重建。

## 源码挂载和调试

两种部署都将宿主工程绑定到 `/ragflow`。Python 修改后 `restart app`；91 前端由 Vite 读取挂载源码，使用原 Web 端口 8088，修改页面无需编译镜像。

Python 环境、模型、生产前端和二进制使用按镜像 ID 区分的只读卷，首次由 Docker 从镜像填充。dev 另有可写的 `web/node_modules` 卷；更新 package.json/lock 后可进入应用执行 `cd web && npm ci`，再重启应用。重建 dev 镜像可固化依赖更新。

生产前端改动执行 `build prod` 并更新标签、重建应用；也支持 `APP_WEB_DIST` 指定宿主已编译目录。Python 包或系统库变化需重建镜像，不能向只读 `.venv` 安装。Tika/tokenizer/版本由镜像补齐到工程忽略文件；生成配置位于 `docker/state`，个人环境持久保存到 `docker/home`。

## 初始化与常用命令

```bash
# 仅首次执行；已有配置拒绝覆盖。同机部署使用相同 IP。
bash docker/docker.sh init --app-ip 192.168.88.91 --storage-ip 192.168.88.92 --app-memory 48g --app-mode dev
bash docker/docker.sh config app
bash docker/docker.sh pull storage
bash docker/docker.sh start storage       # 分离部署在 92
bash docker/docker.sh start app           # 分离部署在 91
bash docker/docker.sh start all           # 同机：先存储、后应用
bash docker/docker.sh status all
bash docker/docker.sh logs app --tail 100
bash docker/docker.sh into app
bash docker/docker.sh into storage mysql
bash docker/docker.sh restart app
bash docker/docker.sh recreate app
bash docker/docker.sh stop all
bash docker/docker.sh down app            # 保留数据卷
```

已有系统沿用私有 env 和原密码。默认 Web/API/Admin 为 8088/9380/9381。应用 into 使用宿主同名 UID/GID 用户、个人标准 `.bashrc` 和免密 sudo；PS1 与 91 vision-pipeline 一致。镜像包含 vim、bash-completion 和 apt 索引，可直接 `sudo apt-get install cmake`。个人 home 重建后保留；临时安装的软件包需写入镜像构建才能长期保留。存储容器保持原生账户和工具。

直接查看镜像文件可执行 `docker run -it --rm --entrypoint /bin/bash IMAGE`，覆盖默认应用入口。正常开发使用 `into app`，获得工程挂载、个人账户和应用环境。

项目名固定为 `ragflow-app` / `ragflow-storage`，拒绝全局清理或 `down -v`。91 旧项目不属于本工程，禁止操作。完整操作、备份和验收见 [operations.md](../files/operations.md)，日志见 [update.md](../files/update.md)。
