# 部署与操作手册

- 用途：归纳可复用的部署、接口、存储及排障操作。
- 核对基准：2026-11-12 本地工程代码；本次未连接 91/92、未执行部署或业务写入。
- 适用范围：本工程的 Linux / Docker Compose v2 Python 应用部署。Go 服务的实现与构建入口需另按当前代码核对，不把下文的 Python 接口契约套用于 Go。
- 关联文档：[问题与修复记录](issue.md)、[更新摘要](update.md)。

工程提供知识库构建、检索与数据挖掘能力，服务于外部 Agent 和 Embedding、Reranker、LLM 微调数据制作。功能以当前实现为准；历史版本号和现场记录不代表全部训练数据制作能力已经交付。

目录：

- [部署边界与目录](#layout) · [工程挂载](#mount) · [初始化与构建](#deploy)
- [容器操作](#inside) · [模型目录](#models) · [备份恢复](#backup)
- [日常验证](#verify) · [应用回退](#rollback) · [源码核对](#source-parity)
- [VS Code](#vscode-container) · [文件解析接口](#file-parsing)
- [数据存储与局部修正](#data-storage) · [Kibana](#kibana)
- [任务排查](#task-troubleshooting) · [残留清理](#knowledgebase-cleanup) · [文档维护](#documentation)

<a id="layout"></a>

## 1. 部署边界与目录

下表为既有部署记录，内存配额和运行状态未在本次重新登录核验；端口默认值已对照 Compose。使用前读取目标环境配置，不能据此推断服务仍在线。

| 主机 | 本工程服务 | 访问地址 |
|----|----|----|
| 192.168.88.91 | ragflow-app，应用上限 48 GiB | Web :8088；API :9380；Admin :9381 |
| 192.168.88.92 | 生产应用 ragflow-app 与共享存储 ragflow-storage，应用上限 6 GiB | Web :8088；API :9380；Admin :9381 |
| 92 存储 | MySQL / Redis / MinIO / ES / Kibana | :3306 / :6379 / :9000、:9001 / :9200 / :5601 |
| Redis Insight | 仅绑定 92 回环地址 | SSH 隧道到 127.0.0.1:5540 |

两端工程路径均为 `/home/cdky/workspace/github/ragflow`。配置在 `docker/env/`，日志、证据、备份分别在 `docker/logs/`、`docker/evidence/`、`docker/backups/`，均不进 Git 或镜像上下文。

- 91 的 ragflow-server、ragflow-mysql、ragflow-minio、ragflow-redis、ragflow-es-01 属于其他工程的 Compose 项目 docker，禁止停止、重建或删除这些容器及数据卷。
- 入口固定选择 ragflow-app / ragflow-storage，不使用全局 prune 或模糊名称批量操作。

- 91 为开发环境，92 为生产环境。开发期间只操作本地和 91，不连接、发布、重启或更改 92。
- 历史部署中，两端共用 92 的业务存储和账号；91 队列为 `te.dev91`，92 为 `te`。通过 91 发起写入仍可能影响共享存储，队列分离不等于数据隔离。
- 开发写入测试必须使用已核实的独立数据库、对象存储、检索索引和队列。下文涉及 92 的命令仅用于单独授权的生产维护。
- 新建 dev 配置时，[init_env.py](../docker/scripts/init_env.py) 生成 `te.dev.<应用IP中的点/冒号改为下划线>`，例如 `te.dev.192_168_88_91`。
- 未显式设置 `RAGFLOW_QUEUE_NAME` 时，[common/constants.py](../common/constants.py) 的 dev 默认值为 `te.dev`，其他模式为 `te`；dev 显式使用 `te` 会被拒绝。实际诊断应读取运行容器的值。

<a id="mount"></a>

## 2. 工程整体挂载与二次开发

- 91 使用 dev 模式，92 使用 prod 模式；两种部署均将宿主工程绑定到 `/ragflow`。Python 修改后执行 restart app。91 的 Vite 直接读取 web 源码，经原有 8088 端口提供页面和热更新，无需重新构建镜像。
- 生产前端由镜像构建生成，修改后构建新的 prod 镜像并 recreate app。

| 容器路径 | 来源 |
|----|----|
| /ragflow | 宿主机工程根目录，可读写。 |
| /ragflow/.venv | 按镜像 ID 区分的只读 Python 依赖卷，首次由 Docker 从镜像填充。 |
| /ragflow/rag/res/deepdoc | 对应镜像的只读 OCR 模型卷。 |
| /ragflow/web/dist、/ragflow/bin | 对应镜像的前端和二进制只读卷；APP_WEB_DIST 可改用宿主机前端产物。 |
| /ragflow/web/node_modules | 仅 dev：按镜像 ID 区分的可写依赖卷，支持 Vite 缓存和 npm ci。 |
| /opt/python、/opt/chrome | 构建时从 third_partys 的官方归档解压的 Python 和 Chrome。 |
| /ragflow/conf/service_conf.yaml | 绑定 docker/state/service_conf.yaml，生成配置不覆盖工程原文件。 |
| /home | 绑定 docker/home，持久保存宿主同名用户的 Bash、Vim 配置和历史。 |
| /ragflow/logs、/opt/ragflow-ops | 日志持久化目录、只读运维脚本目录。 |

整目录挂载会遮住镜像原 /ragflow，因此运行依赖需单独挂载。Tika JAR、tokenizer 缓存和版本文件由镜像 `/opt/ragflow-runtime` 补齐到忽略管理的运行文件，不包含应用源码。镜像 ID 改变会自动创建新依赖卷；旧卷保留供回退，不能盲目清理。

```bash
# 修改 Python 源码后重新加载
bash docker/docker.sh restart app
# dev 前端源码直接编辑，浏览器自动更新；仅依赖变化需要：
bash docker/docker.sh into app
cd web
npm ci
exit
bash docker/docker.sh restart app
```

重建 dev 镜像可固化前端依赖变更。Python 包和系统库变化需要重建镜像，不能向只读 .venv 安装。生产模式不运行 Vite，可重新 build prod 或通过 APP_WEB_DIST 指定宿主已编译目录。历史部署只做了解析队列隔离，数据库仍共享；调试写入前须改用已核实的隔离存储。

<a id="deploy"></a>

## 3. 初始化、构建与部署

在目标主机工程根目录运行。新部署示例要求已准备隔离存储，并确认端口、Compose 项目名与现有服务不冲突；不能在既有 91 环境直接再启动一套同名服务。

### 3.1 新环境配置

```bash
cd /home/cdky/workspace/github/ragflow
# 先由环境提供已确认的隔离存储 IP；不要填写 192.168.88.92。
: "${DEV_STORAGE_IP:?请先设置已核实的隔离开发存储IP}"
bash docker/docker.sh init --app-ip 192.168.88.91 --storage-ip "$DEV_STORAGE_IP" --app-memory 48g --app-mode dev
chmod 600 docker/env/*.env
```

仅首次执行初始化；任何 env 已存在都会拒绝覆盖。分离部署将匹配的 app.env 和 storage.env 安全分发到对应主机；当前已有配置不能重新生成密码。应用配置不包含 MySQL root 密码。

- APP_IP 控制应用绑定地址，APP_WEB_PORT / APP_API_PORT / APP_ADMIN_PORT 默认为 8088 / 9380 / 9381。
- MYSQL_HOST、REDIS_HOST、MINIO_HOST、ES_HOST 使用容器可达的存储 IP；同机仍使用 LAN IP，不能填容器自己的 127.0.0.1。STORAGE_IP 控制存储监听。

### 3.2 镜像与启动

```bash
bash docker/docker.sh fetch
bash docker/docker.sh build dev ragflow-local:dev-20261030 --progress=plain
bash docker/docker.sh build prod ragflow-local:prod-20261030 --progress=plain
# 91 app.env: APP_MODE=dev，RAGFLOW_IMAGE=ragflow-local:dev-20261030
# 92 app.env: APP_MODE=prod，RAGFLOW_IMAGE=ragflow-local:prod-20261030
# 已部署系统切换应用：bash docker/docker.sh recreate app
# 缺少存储镜像时：bash docker/docker.sh pull storage

# 新建隔离部署：在隔离存储主机执行
bash docker/docker.sh config storage
bash docker/docker.sh start storage
# 应用主机执行；已部署应用只按变更需要 recreate，不重复 init
bash docker/docker.sh config app
bash docker/docker.sh start app
# 同机隔离部署，且已确认端口/项目不冲突时：
bash docker/docker.sh config all
bash docker/docker.sh start all
```

- Dockerfile.dev 提供运行环境和前端依赖，Dockerfile 构建生产前端。当前应用构建统一 Linux amd64，从 Ubuntu、本地资源及官方 apt/PyPI/npm 源构建。构建不切换在用应用，也不生成新的共享镜像记录；
- 入口核验镜像模式与 APP_MODE 一致后才允许启动。

存储先等待四项核心服务健康，再设置 Kibana 服务账号和 ES 快照仓库，最后启动管理界面。应用等待健康检查，启动统一使用 --pull never。92 七个 ragflow-storage 数据卷继续复用，单机应用不会创建第二套存储。

### 3.3 日常命令

```bash
bash docker/docker.sh status app
bash docker/docker.sh status storage
bash docker/docker.sh logs app --tail 100
bash docker/docker.sh logs storage --since 30m mysql elasticsearch
bash docker/docker.sh restart app
bash docker/docker.sh recreate app
bash docker/docker.sh stop all
bash docker/docker.sh start all
# 完整生产镜像构建
bash docker/docker.sh build prod ragflow-local:my-release
```

restart 用于加载源码；recreate 用于 env、挂载、镜像变化。all 启动先存储后应用，停止先应用后存储。down 只移除所选项目容器/网络，保留数据卷，拒绝额外的 -v 等参数。exec 为自动化提供非交互入口；人工操作使用 into 后执行原生命令。

<a id="source-build"></a>

### 3.4 官方资源缓存与可选 SSH 隧道

- 资源清单固定官方 URL、版本/提交、大小和 SHA-256。模型来自 InfiniFlow 的 Hugging Face 仓库，NLTK 来自 nltk/nltk_data，Tika 来自 Apache，tiktoken 来自 OpenAI 公共资源。
- 资源下载到 third_partys；有效文件跳过，损坏文件重下，未完成下载不替换原文件。NLTK 的解压文件也逐项校验，缺失时从本地 ZIP 恢复。

```bash
bash docker/docker.sh fetch         # 下载缺失资源并校验
bash docker/docker.sh fetch --check # 只校验，完全不联网
```

third_partys 被 Git 忽略，可复制到其他机器后执行 fetch --check；新机器也可直接 fetch 重建。apt、Python/npm 包使用 BuildKit 缓存，首次安装仍需网络；资源齐全不代表可以完全断网重建镜像。

本地已有 HTTP 代理（示例端口 7897）时，在本地 Windows 终端保持以下 SSH 连接。隧道只绑定 91 回环地址：

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -R 127.0.0.1:17897:127.0.0.1:7897 cdky@192.168.88.91
```

91 首次复制配置样例；已有 build.env 直接编辑：

```bash
cp docker/config/build.env.example docker/env/build.env
chmod 600 docker/env/build.env
# 设置 SSH_TUNNEL_ENABLED=1
# 设置 SSH_TUNNEL_PROXY=http://127.0.0.1:17897
bash docker/docker.sh fetch
bash docker/docker.sh build dev ragflow-local:dev-20261030 --progress=plain
```

- 脚本检查隧道可达后，把标准 HTTP(S)\_PROXY 传给宿主下载进程和 Docker 构建，并使用 host 网络。结束后本地 Ctrl+C 关闭隧道，把 SSH_TUNNEL_ENABLED 改回 0。代理不写入镜像运行环境；
- Docker 拉取 Ubuntu 基础镜像由 daemon 网络负责，必要时单独配置 daemon 代理。

升级资源时更新清单 URL、版本、大小和校验值，再 fetch 和构建。Chrome/Driver 由本地官方归档提供。应用 Dockerfile 只保留 dev/prod 两套；agent/sandbox 的独立沙箱组件不参与应用构建。

<a id="inside"></a>

## 4. 先进入容器，再执行原生命令

每组第一行在目标宿主机工程根目录运行，随后进入容器，`exit` 返回宿主机。应用容器示例用于 91，`into storage` 示例供存储维护人员在 92 使用。凭据由容器环境提供。

<a id="app-user"></a>

### 应用用户、sudo 与环境

- 仅应用容器建立宿主同名用户和主组，UID/GID 与当前调用用户一致；在 91/92 均为 cdky / 1000:1000。用普通用户运行 docker.sh；通过 sudo 调用时读取 SUDO_USER。
- into app 以该用户进入 /ragflow 的登录 Bash，不以 root 进入。需要管理权限时执行 sudo；存储容器保留原镜像用户和工具。

- 镜像包含 sudo、vim、bash-completion、less、git、curl、wget、unzip、procps、iproute2 和 ping。env.sh 配置免密 sudo；
- 首次从 /etc/skel 创建完整个人 .bashrc/.profile，保留标准历史、别名和补全。初始 PS1 与 91 的 vision-pipeline/docker/env.sh 相同：绿色用户名、紫色主机名、青色路径。
- 工程环境变量独立放在用户自己的 .ragflow_env，Vim 使用个人 .vimrc。文件一旦存在，后续 into 不重写，用户可以自由修改。docker/home 绑定到 /home，重建后保留配置。
- 基础镜像占用 UID 1000 的 ubuntu 账户重命名为宿主用户；Python 解释器位于 /opt/python，NLTK 数据迁至 /usr/local/share/nltk_data。

```bash
bash docker/docker.sh into app
id
printf '%s\n' "$PS1"
sudo -n id -u              # 应为 0
python --version
vim --version | head -n 1
type _init_completion     # 交互 Bash 的补全函数
# 编辑工程源码：vim api/实际文件.py
exit
```

应用后台进程的身份不在此次调整范围。Python 依赖和 OCR 模型卷只读；需要新增包时更新依赖声明并重建镜像。sudo 用于容器管理或只读诊断；修改挂载源码时使用当前普通用户，使宿主机文件保持当前 UID/GID。

<a id="apt"></a>

### 在容器内安装软件与定制 Bash

```bash
bash docker/docker.sh into app
sudo apt-get install cmake
# 长期运行或仓库版本变化时，按普通 Ubuntu 主机更新索引：
sudo apt-get update
# 编辑个人配置，当前会话重新加载：
vim ~/.bashrc
source ~/.bashrc
exit
```

- 运行镜像保留 apt 软件包索引，可直接 sudo apt-get install；apt 缓存归 root 管理，普通用户通过 sudo 安装。系统安装包位于容器可写层，容器重建后需重新安装；长期依赖应加入 Dockerfile 的安装步骤。
- 个人环境配置位于绑定的 docker/home，重建后保留。

```bash
PS1='\[\033[01;32m\]\u@\[\033[01;35m\]\h\[\033[00m\]:\[\033[01;36m\]\w\[\033[00m\]$ '
```

### 应用与任务

```bash
bash docker/docker.sh into app
pwd
python /opt/ragflow-ops/inspect_task.py
python /opt/ragflow-ops/inspect_task.py --doc-id 实际文档ID
tail -n 100 logs/ragflow_server.log
exit
```

### MySQL

```bash
bash docker/docker.sh into storage mysql
MYSQL_PWD="$MYSQL_PASSWORD" mysql -u ragflow -D rag_flow
# 在 mysql 提示符：SELECT COUNT(*) FROM document;
# 在 mysql 提示符：quit
exit
```

管理操作使用 MYSQL_PWD="\$MYSQL_ROOT_PASSWORD" mysql -uroot。数据库密码不是 SSH 密码。env 内 ADMIN_DEFAULT_PASSWORD 是初始化密码，用户改密后它不自动更新数据库。

### Redis：业务使用 DB 1

```bash
bash docker/docker.sh into storage redis
REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli -n 1
# Redis 提示符：PING / SCAN 0 COUNT 100 / quit
exit
```

### MinIO

```bash
bash docker/docker.sh into storage minio
mc alias set local http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc admin info local
mc ls local
exit
```

### Elasticsearch 与管理界面

```bash
bash docker/docker.sh into storage elasticsearch
curl -fsS -u "elastic:$ELASTIC_PASSWORD" 'http://127.0.0.1:9200/_cluster/health?pretty'
curl -fsS -u "elastic:$ELASTIC_PASSWORD" 'http://127.0.0.1:9200/_cat/indices?v'
exit
# 本地终端建立 Redis Insight 隧道
ssh -N -L 5540:127.0.0.1:5540 cdky@192.168.88.92
```

生产维护时，Redis Insight 通过隧道访问 `http://127.0.0.1:5540`。ES 字段、向量和评分查询见 [Kibana 查询](#kibana)。

<a id="models"></a>

## 5. 模型目录与配置

<a id="tongyi-sync"></a>

### 通义模型同步范围与规则

- 入口为 [sync_model_catalog.py](../docker/scripts/sync_model_catalog.py)，在 **91 Linux 宿主机**运行；
- Python 3.10 标准库负责操作文件/容器，数据库和 HTTP 依赖使用现有应用容器。在隔离环境先执行 `plan`。91 与 92 共用数据库，`apply/rollback` 会修改共享模型数据，只用于批准的生产维护。

- 官方 [查询模型列表 API](https://help.aliyun.com/zh/model-studio/list-models) 提供分页总数、模态、能力、上下文及下线信息。
- 北京业务空间的新域名为 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1/models`；
- 本地同步脚本固定使用 `https://dashscope.aliyuncs.com/api/v1/models`，历史记录曾验证可用，本次未进行云端请求。
- 工具只向后者发送指定北京实例密钥，并固定 `service_site=asia-pacific-china`、`supports=inference`，不筛除平台上的第三方推理供应商。其他地域或业务空间域名需要先审阅并扩展地域策略，不能直接把密钥转发到任意 URL。

这里同步的是官网目录元数据，不是逐模型推理验收。全量官网条目进入快照；RAGFlow 目录只增加当前适配器具有对应调用路径的模型。账号余额、权限、额度和生成质量仍需独立验收，新项的 `verify=unknown`，不会伪造验证成功。

| 情况 | 处理 |
|----|----|
| 新增模型 | 分页取完全部官方条目，根据能力和现有适配器生成目录项，并注册到指定实例 |
| 规格/能力变化 | 更新上下文预算、模型类型、工具调用和思考标记；已有模型 ID、状态、验证结果及其他自定义 extra 保持 |
| 明确下线且已到生效时间 | 按官方 `offline_time` 或策略中的公告清单删除；列出涉及的流程引用，不自动替换流程模型 |
| 未来下线 | 暂保留，在报告中给出生效时间；维护策略中的公告记录，避免后续来源列表移除条目后丢失下线证据 |
| 旧项在列表缺席 | 保留并报告，不把接口缺席、地域差异或别名差异当作已下线 |
| 无对应适配器或关键规格缺失 | 新项不注册，写入 `excluded`；旧项原样保留并写入 `retained_for_review` |
| 请求失败、分页缺失/重复、总数变化、未知下线结构 | 中止生成计划，不使用残缺数据更新目录 |

- `TR` 同时包含文本 Embedding 和 Rerank，不能全部映射成 embedding。当前仅支持已核对调用协议的文本向量/排序、普通 Chat/Vision、Qwen3-ASR/Fun-ASR-Flash 以及 Sambert TTS。
- 图像/视频生成、实时会话、部分 Omni、异步向量及新音频协议等完整保存在官网快照中，待适配器支持后再扩展 `_normalize`，不能仅增加名称就声称可用。

- `max_tokens` 对 Chat 表示上下文预算，不是最大输出 Token；例如历史官网快照中 `qwen3.8-flash` 的上下文为 1,000,000、最大输出为 131,072；这些数值不是本次重新查询结果。
- 原始全部规格保留在 `official.json`。官方未提供数值的条目使用有来源的补充策略，音频时长/字符限额不会伪造成 Token 上下文。现有 Embedding 适配器还会截断输入，目录规格更新本身不会改变解析或截断算法。

<a id="tongyi-policy"></a>

### 维护策略与上线前准备

[tongyi-sync-policy.json](../docker/config/tongyi-sync-policy.json) 维护以下内容：

- 同步服务商和地域；当前为 `Tongyi-Qianwen` / 中国部署范围。
- 官方下线公告的来源、准确模型 Code 和生效日期。下线清单的首次核查见[历史记录](issue.md#tongyi-retirements)；后续核对[模型下线公告](https://help.aliyun.com/zh/model-studio/model-depreciation)，只补入公告明确列出的名称。
- 官方列表缺少 Token 数值时的补充值和来源，例如 text-embedding 系列参照[同步向量 API](https://help.aliyun.com/en/model-studio/text-embedding-synchronous-api)。接口有明确正数时优先使用接口值；文档出现不同口径时先区分单条、单批次、上下文和输出限制。

先核对脚本、策略和目标目录版本，再运行离线检查：

```bash
cd /home/cdky/workspace/github/ragflow
python3 -m unittest test.unit_test.test_sync_model_catalog
```

- 密钥从指定 `tenant_model_instance` 读入容器内存，不放在命令行或快照中。操作目录为 0700、备份/计划文件为 0600。运行前停止提交新的解析任务；
- `apply/rollback` 检查运行中的文档和 `te` 队列，未覆盖 91 的 `te.dev91`。维护人员须暂停两端任务提交，并按[队列检查](#task-queues)确认两端无在途工作。

<a id="tongyi-plan"></a>

### 生成完整快照与差异预览

```bash
cd /home/cdky/workspace/github/ragflow
run="docker/backups/tongyi-sync-$(date +%Y%m%d-%H%M%S)"
python3 docker/scripts/sync_model_catalog.py plan \
  --instance-id 实际实例ID \
  --work-dir "$run"
```

`plan` 只读取官网/数据库并写入新的工作目录，已有目录会拒绝覆盖。检查以下文件：

| 文件 | 用途 |
|----|----|
| `official.json` | 全部分页、request_id、官网总数、原始模型规格与下线时间 |
| `catalog.before.json` / `catalog.after.json` | 完整目录备份和候选目录，其他服务商内容不变 |
| `report.json` | 新增、更新、删除、未来下线、未支持/待复核项及被删除模型的流程引用 |
| `plan.json` | 实例范围、原/目标注册行、文件和策略哈希，用于应用与回退 |

- 重点审阅 `add/update/remove`、`retained_for_review`、`scheduled_retirements`。新 API 协议不能根据名字猜测，须核对 `rag/llm/` 中对应适配器再修改映射规则。
- 需要修改策略或代码时生成新的计划，避免对旧快照手工改 ID 或记录。

<a id="tongyi-apply"></a>

### 应用、重新加载与验收

```bash
python3 docker/scripts/sync_model_catalog.py apply --work-dir "$run"
python3 docker/scripts/sync_model_catalog.py verify --work-dir "$run"
```

- 应用过程依次执行：检查计划未超过 24 小时、策略/目录未变化且未跨越新的下线时刻 → 检查任务空闲 → 锁定并核对指定实例原记录 → 在事务中增量新增/更新/删除 → 原子替换宿主目录文件 → 重启目标应用 → 等待健康状态。
- 数据库比较不通过即拒绝写入，避免覆盖用户在计划生成后的配置修改；不会重建整个模型实例或重置现存 ID。

工程目录整体 bind mount 到容器，原子替换目录中的文件可直接被容器看到；工具使用 `docker/docker.sh restart app` 重新加载 API/Worker 的内存目录。无变化时跳过本次应用重启。

`verify` 核对数据库、宿主文件、容器挂载文件和应用健康状态。页面刷新后可在模型管理中查看新增项；用已登录会话检查两接口：

```text
GET /api/v1/providers/Tongyi-Qianwen/instances/实际实例ID/models
GET /api/v1/providers/Tongyi-Qianwen/instances/实际实例ID/models?supported=true
```

验收后再生成一次新计划，确认新增/更新/删除均为 0、`db_changed=false`、前后目录哈希相同。重复计划仍会请求官网，如果官网恰好有变化，应审查新差异，不能强行凑成零。

<a id="tongyi-rollback"></a>

### 同步工程副本与回退

共享存储只执行一次数据库同步。批准的生产维护中，核对差异后同步两端的 `conf/llm_factories.json`，由相应维护人员重载应用并验证两端目录一致。工作目录和快照保存在私有备份目录。

数据库事务、宿主文件替换和应用重启分步执行。任一步骤失败都保留备份，`operation.json` 标记已执行阶段；不要反复尝试覆盖异常状态。可先检查错误，或在同一工作目录执行：

```bash
python3 docker/scripts/sync_model_catalog.py rollback --work-dir "$run"
python3 docker/scripts/sync_model_catalog.py verify --work-dir "$run"
```

回退仅接受原/目标两种已知状态；若用户之后改过模型行或目录，会拒绝覆盖。成功回退恢复原记录及原目录并重新加载，`verify` 自动验收同步前版本。重复回退仍会重新加载，确保上次加载失败后可恢复容器挂载。回退后按同一维护流程同步两端的目录副本。

<a id="tongyi-quota"></a>

### 免费额度限制与按量调用

- `AllocationQuota.FreeTierOnly` 表示免费额度用完即停限制，与余额不足分开排查。
- 2026-11-12 核对的官方说明：开通百炼前须完成实名认证，未实名不发放免费额度；用完即停默认关闭，开启后额度耗尽会返回该 403 错误。[免费额度规则](https://help.aliyun.com/zh/model-studio/new-free-quota)
- 开关不显示还可能因为额度已耗尽、过期或该模型不提供免费额度，不能仅据此认定未实名。具体错误按[官方错误码](https://help.aliyun.com/en/model-studio/error-code)核对。

1. 用 **API Key 所属账号**在电脑端进入[北京地域免费额度页](https://bailian.console.aliyun.com/cn-beijing/costing-balance/free-quota)，核对目标模型 Code、剩余额度、过期时间和开关状态。
2. 确认需要继续付费调用及预算后，关闭该模型的“免费额度用完即停”。主线与日期快照分别核对；批量操作只勾选本次目标。
3. 等待云端设置生效，再做最小调用验证并检查用量/账单。它不是 RAGFlow 的环境变量，无需为此重启应用。
4. 若仍报错，检查密钥所属账号、地域、模型与响应错误码，保留 request_id 排查。不要因开关关闭就假定账号有余额或模型已有权限。

<a id="embedding"></a>

### 本地 Qwen3 Embedding 配置

历史配置中的模型服务为 `192.168.88.169:9502`，不属于 91/92 存储部署；模型名 `qwen3-text-embedding`、输入 2048 Token、输出 1024 维均为当时记录。本次未探测该服务，配置前先核实实际服务规格。

1.  在“设置 → 模型提供商”添加 VLLM 实例，名称可用 local-qwen3-embedding，Base URL 填 http://192.168.88.169:9502/v1。密钥只填服务分配的值，不加 Bearer 前缀。
2.  选择 qwen3-text-embedding，类型为 Embedding，最大 Token 数填 2048；不要将向量维度 1024 当作 Token 限制。
3.  验证模型后保存，按需设置全局默认及具体知识库。全局默认不会替换已有知识库的模型。

Base URL 不要加 /embeddings。服务须从应用容器可达。即使新旧模型都是 1024 维，向量空间也不相同；先用独立知识库验证，迁移时为整库原文、编译结果和 Graph 统一重建向量，不能直接改 embd_id 混用旧向量。

<a id="backup"></a>

## 6. 备份与恢复

以下共享存储备份与恢复由生产维护人员执行。开发环境验证恢复流程时使用独立的测试存储。

### 6.1 在线 MySQL 备份

```bash
bash docker/docker.sh into storage mysql
umask 077
MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction \
  --routines --events --triggers --set-gtid-purged=OFF --databases rag_flow \
  > /tmp/rag_flow.sql
exit
# 宿主机取出备份，请使用唯一文件名避免覆盖
mkdir -p docker/backups
chmod 700 docker/backups
docker cp ragflow-storage-mysql-1:/tmp/rag_flow.sql docker/backups/rag_flow.sql
chmod 600 docker/backups/rag_flow.sql
```

在线 SQL 备份不覆盖 ES、MinIO 和 Redis，不能作为全系统一致性备份。

### 6.2 全存储冷备

```bash
# 等待当前任务结束，两端应用主机分别执行
bash docker/docker.sh stop app
# 92：列出全部应用 API 地址
APP_STOPPED=1 APP_URLS="http://192.168.88.91:9380 http://192.168.88.92:9380" \
  bash docker/scripts/backup.sh
```

- 脚本检查端点不响应、七个卷确属 ragflow-storage 后停止存储，只读归档 mysql_data、es_data、es_snapshots、minio_data、redis_data、kibana_data、redisinsight_data；
- 校验 gzip 并生成 SHA256SUMS。结束后只恢复原先运行的存储容器，不自动启动应用。检查状态健康后再分别启动两端应用。

APP_STOPPED=1 是操作者确认。网络不可达不能证明远端 Worker 已停，应检查每台主机的容器实际状态。同一备份集合还须保存两端 app.env、storage.env、源码版本与差异和镜像记录，权限 600。

### 6.3 恢复顺序

1.  在独立位置校验 SHA256SUMS 和压缩包，先恢复到独立测试卷，不能覆盖在用数据。
2.  使用备份对应版本的存储镜像。冷备数据解包到各自空卷；在线 SQL 导入独立 MySQL 实例。物理数据库目录不能直接跨大版本复制。
3.  数据、env 密钥和代码作为一组切换。只恢复 MySQL 会造成 ES 向量、MinIO 对象、Redis 任务不一致。
4.  停止全部应用写入，验证恢复存储健康和业务对象关联后再切换连接配置，重建应用。
5.  使用独立探针和真实只读查询验收。保留旧卷以便回退，不运行全局清理。

<a id="verify"></a>

## 7. 日常验证

1.  核对资源清单及应用健康。
2.  进入容器运行离线资源检查；该检查不替代模型、业务负载或完整灾备验证。
3.  dev 确认 Vite 可达，prod 检查部署的静态资源与 API。

```bash
bash docker/docker.sh fetch --check
bash docker/docker.sh status app
bash docker/docker.sh into app
python /opt/ragflow-ops/verify_runtime.py
exit
curl -f http://192.168.88.91:8088/@vite/client
curl -f http://192.168.88.91:9380/api/v1/system/healthz
```

<a id="rollback"></a>

## 8. 应用构建与模式切换回退

1.  变更前保存当前源码及差异、私有 app.env、镜像标识和容器配置到受限备份目录。
2.  回退前停止本工程 app，将归档解压到独立位置核对，恢复匹配的源码、私有 env 与旧镜像。
3.  仅按本次变更清单处理新增受管文件，保留私有 env/home、原依赖卷和业务数据。
4.  重新创建 app，检查健康、静态资源和只读业务查询；历史备份见 [排查记录](issue.md)中的对应条目。

<a id="source-parity"></a>

## 9. 运行资源与源码核对

官方资源从 [构建缓存](#source-build)恢复，Tika JAR 与配套 MD5、tokenizer 缓存及 VERSION 由运行镜像补齐。依赖卷按[工程挂载规则](#mount)重建；既有私有 env 和业务数据从[受控备份](#backup)恢复。

- 源码比对使用全部 Git 跟踪文件和未忽略新文件的 SHA-256，不只抽查改动文件。文本统一 CRLF/LF 后比较，二进制按原始字节比较；两个链接比较实际目标。
- Windows 上由 WSL 创建的 CLAUDE.md 和 testdata 使用 LX reparse 格式，Windows Git 可能显示无法读取；
- 核验程序直接读取 reparse 元数据，目标分别为 AGENTS.md 和 ../testdata，与 Linux 一致。

```bash
# 每端在工程根生成到工程外；不得将清单输出到源码目录内。
python3 scripts/source_manifest.py > /tmp/ragflow-source.json
sha256sum /tmp/ragflow-source.json
```

本地 PowerShell：

```powershell
python scripts/source_manifest.py > "$env:TEMP/ragflow-source.json"
Get-FileHash "$env:TEMP/ragflow-source.json" -Algorithm SHA256
```

- 源码一致不要求两台应用的 app.env、运行镜像 ID 或运行日志相同。91 的 APP_IP/内存上限为 192.168.88.91/48g，92 为 192.168.88.92/6g；存储地址和配套凭据须匹配。
- 91 为 dev、92 为 prod，私有 APP_MODE/RAGFLOW_IMAGE 因用途不同而不同；运行镜像记录按主机用途分别维护。

<a id="offline-check"></a>

### 9.1 离线运行资源检查

```bash
bash docker/docker.sh into app
python /opt/ragflow-ops/verify_runtime.py
exit
```

当前 `verify_runtime.py` 有 9 项检查，涵盖挂载源码、Python 与连接库、Tika 校验、tokenizer 离线编码、ONNX 模型、对应前端、用户环境及工具。此检查不替代完整源码构建或业务负载测试；历史验证结果见 issue.md。

<a id="vscode-container"></a>

## 10. Windows VS Code 连接应用容器

- 91 的应用使用整工程挂载：宿主机 `/home/cdky/workspace/github/ragflow` 对应容器内 `/ragflow`。
- 先在 Windows VS Code 安装 Remote - SSH 与 Dev Containers，使用 Remote - SSH 连接 91，再选择 `Dev Containers: Attach to Running Container...`，选择 `ragflow-app-ragflow-1`，打开容器内 `/ragflow`。
- 不要选择 91 其他 RAGFlow 容器。可从终端检查容器身份：`id`、`pwd`、`git status --short`。

<a id="vscode-attach"></a>

### 10.1 附加配置、扩展和解释器

- 本工程现有容器由 Compose 启动，使用“附加到运行中容器”的配置，不能假设仓库里的 devcontainer.json 会自动应用。
- 附加后执行 `Dev Containers: Open Named Configuration File`，将下列内容合并到名称级配置并保存；已有配置请保留其他设置。
- 名称级配置保存在 VS Code 所在的客户端环境，必要时也可使用 `Dev Containers: Open Container Configuration File` 配置镜像级选项。两者分别按容器名或镜像生效，具体位置由 VS Code 管理。
- 以下 `cdky` 应换成对应主机映射到容器的实际用户名。保存后断开并重新附加，使 remoteUser 生效，不必重建或重启业务容器。

```json
{
  "workspaceFolder": "/ragflow",
  "remoteUser": "cdky",
  "extensions": [
    "ms-python.python",
    "ms-python.vscode-pylance"
  ],
  "settings": {
    "python.defaultInterpreterPath": "/ragflow/.venv/bin/python",
    "python.analysis.typeCheckingMode": "basic",
    "python.analysis.autoImportCompletions": true,
    "python.analysis.indexing": true,
    "editor.renderValidation": true,
    "git.enabled": true,
    "git.decorations.enabled": true,
    "explorer.decorations.badges": true,
    "explorer.decorations.colors": true,
    "terminal.integrated.defaultProfile.linux": "bash",
    "cmake.sourceDirectory": "${workspaceFolder}/internal/binding/cpp"
  }
}
```

- 仓库的 [vscode-attach.example.json](../docker/config/vscode-attach.example.json) 混合了工作区设置与容器附加字段，类型检查为 `off`，与上面的完整附加配置不同。不要整份直接复制到附加配置；
- 工作区选项放 `.vscode/settings.json`，容器选项按上面的 `settings` 层级组织。按需在容器侧安装/启用 Python 与 Pylance，Windows 侧安装的扩展不一定运行在容器中。
- 命令面板执行 `Python: Select Interpreter`，选择 `/ragflow/.venv/bin/python`；defaultInterpreterPath 是首次选择的默认值，不会强制覆盖 VS Code 已记住的选择。
- 终端用 `/ragflow/.venv/bin/python -c 'import sys, peewee; print(sys.executable, peewee.__file__)'` 核实。`.venv` 是只读镜像依赖卷；
- 缺包需按工程流程更新依赖并重建镜像，不应通过 sudo 往该卷安装。

- 上面的附加配置使用 `basic` 类型检查，红线和导入错误不被整体隐藏；要查看诊断，打开 `View: Problems`，检查来源与规则名。实际个人工作区的 `.vscode/` 已被 Git 忽略，文件可能与本地或另一台服务器不同；
- 请合并配置，不要直接覆盖别人的配置。CMake 路径应为 `${workspaceFolder}/internal/binding/cpp`，容器里不可使用宿主机的绝对路径。应用端口可直接使用主机映射的 8088、9380、9381，按需手动转发，避免重复暴露。

<a id="file-parsing"></a>

## 11. 外部 Agent 文件解析接口

- 适用于 Python API。接口复用现有解析器，返回文本，不创建知识库、文件记录或入库索引。底层 PDF/DOCX/Markdown 解析可能使用租户视觉模型；无入库不代表无模型调用，真实格式验收需核对模型配置。
- 外部 Agent 可使用 [文件解析 Skill](../sdk/skills/ragflow-parse-file/SKILL.md)。

<a id="parse-contract"></a>

### 接口契约

两个接口均使用已有用户 API Key：`Authorization: Bearer <API Key>`，不是登录密码或 Beta token。

- `GET /api/v1/files/parse`：返回 `data.extensions`、`max_file_bytes`、`layout_modes`、`format`。
- `POST /api/v1/files/parse`：`multipart/form-data`，恰好一个 `file`；可选 `layout_recognize`，值为 `Plain Text`（默认）或 `DeepDOC`。其他字段、多个文件、空文件、未知扩展名拒绝。

- 单文件最大 20 MiB；multipart 整体最大 20 MiB + 64 KiB，部署的全局请求或代理限制更小时以更小值为准。
- 支持 pdf/doc/docx/txt/md/markdown/html/htm/csv/xls/xlsx/json/jsonl/epub；扩展名支持不等于任意内容均可解析。Office、PDF、OCR 仍依赖服务端现有解析组件。
- 普通文本模式不保证读取扫描 PDF，扫描件需 DeepDOC。响应为文本，不承诺版面坐标、图片或无损还原。

成功示例：

```json
{"code":0,"data":{"filename":"example.txt","size":5,"format":"text","content":"\n -----------------\nFile: example.txt\nContent as following: \nhello","layout_recognize":"Plain Text"}}
```

文本保留现有解析器生成的文件标题、分块拼接和表格标记。客户端应同时检查 HTTP 状态和 `code`；文本/HTML 为不可信文档内容，不能直接作为指令或未经清洗插入页面。

- 错误：400 输入错误；413 文件/请求过大；415 请求格式错误；422 解析失败（详细异常仅在服务日志）。认证失败沿用系统现有认证返回约定。同步调用通过现有有界长任务线程池执行；没有作业查询/取消接口，客户端超时不意味着底层解析终止，也没有结果持久化或自动重试。
- 适合小文件即时解析，批量长任务仍应使用知识库异步入库流程。

<a id="parse-example"></a>

### 开发环境调用

先运行本地契约测试。发布到 91 后，用已有 API Key 查询能力并上传测试文件。

```bash
export RAGFLOW_BASE_URL=http://192.168.88.91:9380
# RAGFLOW_API_KEY 由调用环境安全注入，不把密钥写入脚本或文档
curl --fail-with-body -H "Authorization: Bearer ${RAGFLOW_API_KEY}" \
  "${RAGFLOW_BASE_URL}/api/v1/files/parse"
printf 'hello agent\n' > /tmp/ragflow-parse-example.txt
curl --fail-with-body --max-time 300 \
  -H "Authorization: Bearer ${RAGFLOW_API_KEY}" \
  -F 'file=@/tmp/ragflow-parse-example.txt' \
  -F "layout_recognize=DeepDOC" \
  "${RAGFLOW_BASE_URL}/api/v1/files/parse"
```

- 预期 `code=0` 且 `data.content` 包含 `hello agent`。随后用带文本层 PDF、扫描 PDF（DeepDOC）、DOCX、XLSX 各一份做真实解析验收，检查中文、表格和空结果。
- GET 404 表示代码未发布、未重启或代理路径错误，不能通过更换 API Key 修复。

<a id="parse-validation"></a>

### 本地验证

```bash
python -m pytest test/unit_test/api/apps/restful_apis/test_file_parse_api.py -q
python -m ruff check api/apps/restful_apis/file_parse_api.py api/apps/services/file_parse_service.py test/unit_test/api/apps/restful_apis/test_file_parse_api.py
```

- 测试使用真实 Quart multipart 请求，替换认证加载与原生解析依赖，验证接口契约及租户传递；不替代真实 API Key、数据库或 OCR 集成验收。
- 请求体限制沿用 [Quart 请求处理机制](https://quart.palletsprojects.com/en/stable/discussion/dos_mitigations/)。

<a id="data-storage"></a>

## 12. 数据存储与局部修正

t4 为 2026-10-27 的只读案例。下列命令里的 ID、记录数和请求体来自当时的快照。执行修正前须重新定位对象、核对运行记录，并确认写入目标属于获准的隔离环境。[排查记录](issue.md#t4-correction)

<a id="storage-mapping"></a>

### 1. 存储分工与关联

应用位于 91；本部署的 MySQL、MinIO、Elasticsearch、Redis 位于 92。不是每个处理步骤对应一个独立数据库。

| 数据 | 实际存储 | 结构及关联 |
|----|----|----|
| 知识库、文档、流程定义 | MySQL `rag_flow.knowledgebase/document/user_canvas` | `document.kb_id → knowledgebase.id`；`document.pipeline_id → user_canvas.id`；库的 `embd_id` 指定编码模型，文档自身的 `pipeline_id` 决定实际流程 |
| 文件元数据、文件与文档关系 | MySQL `file/file2document` | 文件 ID 与 document ID 是不同概念；文件关联表连接两者 |
| 原始 DOCX、图片二进制 | MinIO 对象 | t4 原文件桶是 KB ID，对象键为 `document.location`；图片 chunk 的 `img_id=imagetemps-UUID` 指向桶 `imagetemps`、键 `UUID` |
| Parser、Chunker、Extractor、Tokenizer 中间输出 | 执行期间内存；运行快照在 MySQL `pipeline_operation_log.dsl` | 输出位于 `components[节点ID].obj.params.outputs[输出名].value`；JSONField 在 MySQL 中为 LongText。快照含文本、摘要、分词等；当前保存前递归移除 `q_<维度>_vec`，不能当向量备份 |
| 最终 chunk、全文检索字段、向量 | Elasticsearch `ragflow_<tenant_id>` | 同一 ES 文档：`_id/id`、`doc_id`、`kb_id`、`content_with_weight`、`content_ltks/content_sm_ltks`、`q_1024_vec`、`img_id`、`chunk_order_int` 等 |
| Compiler 实体、关系、文档图谱快照 | 同一个 ES 索引中的其他文档 | `compile_kwd=hypergraph`；`knowledge_graph_kwd=entity/relation/graph`；实体/关系有 `source_chunk_ids`，关联源 chunk；`compilation_template_ids` 关联 MySQL 编译模板 |
| 知识库级合并图谱 | 同一个 ES 索引，另行生成 | `knowledge_graph_kwd=dataset_graph` 及 `scope_kwd=dataset` 的实体/关系，与文档级图谱分开；t4 此次尚无这些记录 |
| 任务、统计和历史记录 | MySQL `task/document/knowledgebase/pipeline_operation_log` | `task.doc_id`、`task.chunk_ids`；chunk 数量是普通块数量，不等于 ES 总行数 |
| 队列、短期运行轨迹、缓存 | Redis DB 1 | 队列如 `te.dev91.0.common`（91）和 `te.0.common`（92）；轨迹键 `<flow_id>-<task_id>-logs`，更新时 TTL 为 30 分钟；不是持久化 chunk 正文库 |

- 关联主线：`KB → Document → Pipeline/Task/OperationLog → Chunk`；图谱通过 `source_chunk_ids → Chunk.id`，图片通过 `Chunk.img_id → MinIO bucket/object`。
- 这些多数是应用层字段关联，**不存在修改上游记录就自动级联重算的数据库外键触发器**。Parser JSON 项通常没有最终 chunk ID；切块合并后，并非每一项都具有可直接追踪的一对一行级外键。

2026-10-27 现场记录中的 ES mapping（当前实例应重新查询）：

```json
{
  "content_with_weight": {"type": "text", "index": false, "store": true},
  "content_ltks": {"type": "text", "analyzer": "whitespace"},
  "content_sm_ltks": {"type": "text", "analyzer": "whitespace"},
  "q_1024_vec": {"type": "dense_vector", "dims": 1024, "index": true, "similarity": "cosine"},
  "doc_id": {"type": "keyword"},
  "kb_id": {"type": "keyword"},
  "source_chunk_ids": {"type": "keyword"}
}
```

BM25 使用 ES 对分词字段建立的倒排索引和相关性统计，不是一张独立的 BM25 数据表，也没有一个可手改的固定 BM25 分数。只改 `content_with_weight` 不会修正全文检索，因为该字段明确 `index=false`。本次向量也在 ES，无额外独立向量数据库。

<a id="storage-update"></a>

### 2. 修改后是否自动联动

| 修改入口 | 切块 | 编码/全文索引 | 文档 Graph | 原文件/上游历史 |
|----|----|----|----|----|
| 直接改 MySQL 日志 DSL 或 MinIO 内容 | 不重算 | 不重算 | 不重算 | 只改变直接写入对象 |
| 流程结果页编辑 Parser 输出，未点击重跑 | 不重算，改动仅在页面状态 | 不重算 | 不重算 | 未提交运行请求 |
| Parser 结果点击“从当前步骤重新运行” | 以修改后的 Parser 输出重新切块 | 后续节点及入库重新执行 | 下游存在 Compiler 时重新编译 | 不覆盖原文件 |
| 流程结果页编辑 TokenChunker 输出并重跑 | 保留所提交的整份切块结果，跳过该切块节点 | 下游 Extractor/Compiler/Tokenizer 按流程运行 | 重新编译当前文档 | 不自动回写 Parser 原输出 |
| 最终 chunk 编辑/PATCH 接口 | 保留同一个 chunk ID，不重新划分边界 | 重新编码该块并更新分词字段 | **不更新**实体、关系或图谱 JSON | 不更新 Parser/Chunker 运行快照、MinIO 原文件 |

<a id="chunk-patch-contract"></a>

#### 单块接口的确切行为

`PATCH /api/v1/datasets/{kb}/documents/{doc}/chunks/{chunk}` 在 [chunk_api.py](../api/apps/restful_apis/chunk_api.py) 中：

1.  校验库、文档、chunk 归属；保持 chunk ID。
2.  从提交正文生成 `content_ltks/content_sm_ltks`。
3.  用该文档所属库的 Embedding 模型重新编码。t4 非 QA，当前请求是 `0.1 × 文件名向量 + 0.9 × 正文向量`，与 t4 Tokenizer 的权重一致。
4.  更新 ES 同一记录的正文、分词和 `q_1024_vec`；ES 在 refresh 后将新分词用于检索，无需全库重建。

- 注意：接口不会重新生成摘要、问题、关键词、Graph；现有问题/关键词只有显式提交时才更新。若提交 `questions`，其非空内容可作为编码输入。通用接口也不重放其他流程自定义的字段/权重策略；
- 此处结论已对照 t4 的 `fields=[text]`、文件名权重 0.1。普通 GET chunk 会隐藏向量和分词字段，严格验收要读取 ES。
- 当前 PATCH 没有检查底层 update 返回的布尔值，不能只看 HTTP 200/业务码 0 就断言写入成功，必须回读。

<a id="pipeline-rerun-scope"></a>

#### “从当前步骤重新运行”的实际范围

- [rerun_agent](../api/apps/restful_apis/agent_api.py) 会先删除**当前文档**的 ES 记录及旧任务，移除数据集导航引用、重置统计，再以请求 DSL 排队；
- [Pipeline.run](../rag/flow/pipeline.py) 复用选中节点输出，从它的下游执行。因此这不是单个数组项的增量重跑，也不是后台自动监听字段变化。重跑过程中当前文档会暂时无法完整检索，失败也不会自动回滚。

文档级 Compiler 重新执行后，知识库级合并图谱仍是独立任务。只重新生成 Artifacts Graph 不能替代源 chunk 的重编码，也不能保证修复尚未重新编译的文档实体。

<a id="t4-snapshot"></a>

### 3. t4 实际定位

| 对象 | 2026-10-27 快照值 |
|----|----|
| KB | `3c845f96d1ac11f18715a9a4fa662e3a`，名称 `t4` |
| 文档 | `4ea43b56d1ac11f18715a9a4fa662e3a`，`成都开源计算-初步技术方案模板.docx` |
| 流程 | `83edbb8ad1ab11f18715a9a4fa662e3a`，`model_pip_new` |
| 运行日志 | `a9fc07aed1ac11f1a42b59051324d298` |
| 目标 chunk | `cbae5b080fb2ca3b`，`chunk_order_int=20`（第 21 块） |
| Parser 输出 | `Parser:HipSignsRhyme.outputs.json.value[83].text`（第 84 项） |
| Chunker 输出 | `TokenChunker:PublicBusesYawn.outputs.chunks.value[20].text` |
| 当时正文 | `图1. 迪丽热巴` |
| 目标正文 | `图1. 古力娜扎` |
| Embedding | `qwen3.7-text-embedding-flash`，ID `2156bcce3aa54a19b17567e5ab447421`，实际向量 1024 维 |
| ES 索引 | `ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee` |

- 核查时 t4 只有一个文档：25 个普通 chunk（13 文本、8 表格、4 图片），另有 20 实体、17 关系、1 文档图谱快照，共 63 条 ES 记录。没有库级合并图谱。目标说明是独立文本块；
- 相邻图片块为 `40e88a0317ce6554`，图片对象为 `imagetemps/6eaafd5ed1ac11f1a42b59051324d298`，两块不共享 `img_id`，图谱关系引用二者。

必须检查的图谱影响范围：

| ES ID | 影响 |
|----|----|
| `bb5a8b338d7de72c` | 人物实体 `name_kwd=迪丽热巴`，引用目标 chunk |
| `52ff36403a0473fd` | 关系起点、描述含旧姓名，引用说明块和图片块 |
| `44c44bdde187e15d` | `@我是娜扎` 实体的英文描述含 `Dilraba Dilmurat`；只引用图片块，单凭目标 `source_chunk_ids` 会漏掉它 |
| `0a4b64636adca88c` | 汇总图 JSON 中的实体/关系及英文描述仍含旧身份 |

- 此外，Extractor `Extractor:RedLionsSmash` 的 user prompt 仍是 `要总结的文本：\n[在此处插入文本]`，没有正文变量。目标块 summary 是“您好，您似乎忘记粘贴需要总结的文本了……”；
- Tokenizer 优先用 summary 做全文分词，所以当前正文与 BM25 文本不一致。向量使用 `fields=[text]`，并非也用该错误摘要。这是本次需一起考虑的索引问题。

<a id="chunk-patch"></a>

### 4. 路线 A：只改一个最终 chunk 和检索索引

适用于暂时只修正正文、向量和 BM25；**Graph 不会随之修复**。若要求图谱也一致，直接采用路线 B，无需先执行 A。

1.  确认文档不在解析、没有并发编辑。备份目标 ES 原始记录（包含向量/分词），以及本节列出的图谱记录和运行 DSL；普通 GET chunk 的返回不包含完整索引字段。
2.  在最终 chunk 编辑入口，将目标块整段改为 `图1. 古力娜扎` 并保存；务必区分流程时间线中的中间结果编辑。
3.  或在本地 PowerShell 通过以下接口提交。令牌用当前 RAGFlow 登录令牌或应用 API Key，**不是阿里云模型密钥**；通过终端安全注入 `$env:RAGFLOW_TOKEN`，不要写入项目文件。

```powershell
$base = 'http://192.168.88.91:9380/api/v1'
$kb = '3c845f96d1ac11f18715a9a4fa662e3a'
$doc = '4ea43b56d1ac11f18715a9a4fa662e3a'
$chunk = 'cbae5b080fb2ca3b'
if (-not $env:RAGFLOW_TOKEN) { throw '请先设置 RAGFLOW_TOKEN' }
$uri = "$base/datasets/$kb/documents/$doc/chunks/$chunk"
curl.exe --fail-with-body -sS -X PATCH $uri `
  -H "Authorization: Bearer $env:RAGFLOW_TOKEN" `
  -H 'Content-Type: application/json' `
  --data-binary '@docker/evidence/t4-chunk-patch.json'
```

历史记录曾准备该请求文件但未提交；它不属于 Git 跟踪制品，本次未确认文件仍存在。执行前以 UTF-8 重建并审核，内容为 `{"content":"图1. 古力娜扎"}`。

4.  GET 同一 URL 回读，正文应为新文字，ID 仍为 `cbae5b080fb2ca3b`；ES 回读确认两个分词字段不再是无正文提示，向量仍为 1024 维且已重新生成。等待 ES refresh 后做仅全文检索验收，再做向量检索验收。不要用“整个 t4 搜不到旧名”验收 A，因为 Graph 仍有旧名。
5.  如需回退，维护窗口中将备份的完整 ES 行按原 `_id` 恢复并 refresh；简单 PATCH 回旧正文会再次生成索引，**不会恢复原有错误 summary 分词**，与精确回滚不同。

<a id="pipeline-rerun"></a>

### 5. 路线 B：跳过解析/切块，重建当前文档下游，包含 Graph

- 这是当前已有流程能提供的完整一致性修正路径。它复用原来的 25 个切块及图片描述，重新运行 `Extractor → Compiler → Tokenizer → 入库`，不重新执行 File、Parser、TokenChunker，不重新识别四张图片，不处理其他文档。
- 但 **t4 只有一份文档，因此仍会重新编码这 25 个 chunk 并重新编译该文档图谱**；不能称为仅一块的增量更新。后续模型调用会使用账号推理额度。

<a id="rerun-backup"></a>

#### 5.1 备份与准备

- 备份本文件所有 63 条 ES 行、关联 MySQL 文档/任务/运行 DSL。历史记录记载只读原始快照保存于本地忽略目录 `docker/evidence/t4-snapshot.json`，含向量；进一步的原文件/代码/mapping 核验记载于 `t4-details.json`。这些私有工件本次未复核；执行前应重新取快照，不能用旧快照覆盖之后的用户修改。
- 确认文档空闲。保存上游结果不改原始 DOCX：MinIO 原文件中仍有一次旧姓名，直接从 File 再解析会恢复旧题注。应另行维护修正后的源文件版本，避免未来重解析覆盖人工修正。
- 历史记录曾根据现场日志生成 `docker/evidence/t4-rerun-request.json`，当时未提交。执行前必须基于最新日志重建并审核该请求，不能假定旧文件仍存在；修改位置参考下表。

| 请求体内位置 | 修正 |
|----|----|
| Parser 的 `outputs.json.value[83].text` | 改为新题注，保持此次运行记录上游说明一致 |
| TokenChunker 的 `outputs.json.value[83].text` | 同步其传递的 Parser JSON 副本 |
| TokenChunker 的 `outputs.chunks.value[20].text` | 改为新题注，其他 24 块原样保留 |
| Extractor 的 `params.prompts[0].content` | `要总结的文本：\n{TokenChunker:PublicBusesYawn@chunks}` |
| 顶层 `id` | 当前运行日志 ID，**不是 pipeline ID** |
| 顶层 `component_id` | `TokenChunker:PublicBusesYawn`，复用此节点输出，从 Extractor 开始执行 |

- Extractor 会识别此列表变量，并在循环内用各块的 `text` 替换变量值。仅在流程画布修改提示词不会自动更新旧日志 DSL；此次请求已同时修正其运行 DSL。
- 日后从原文件执行仍读取画布配置，需在 `model_pip_new` 中也将正文变量绑定为 TokenChunker 的 chunks（通过变量选择器），避免继续产生无正文摘要。

如果通过 UI 修改：进入该文档的流程结果，选择 TokenChunker，修改第 21 块后点击“从当前步骤重新运行”。但当前 UI 只替换选中节点，不会一并修正旧日志里的 Extractor 提示词，所以本例推荐使用已审阅的完整 DSL 请求，而非直接点击旧运行记录重跑。

<a id="rerun-check"></a>

#### 5.2 提交前核对当前运行记录

```powershell
$base = 'http://192.168.88.91:9380/api/v1'
$kb = '3c845f96d1ac11f18715a9a4fa662e3a'
$log = 'a9fc07aed1ac11f1a42b59051324d298'
if (-not $env:RAGFLOW_TOKEN) { throw '请先设置 RAGFLOW_TOKEN' }
curl.exe --fail-with-body -sS "$base/datasets/$kb/ingestions/$log" `
  -H "Authorization: Bearer $env:RAGFLOW_TOKEN" `
  -o docker/evidence/t4-current-log.json
```

- 确认响应业务码为 0、文档 ID 相符，且 `data.dsl` 与 `t4-snapshot.json` 中该日志的原 DSL 语义一致；同时确认没有更新的解析记录或并发修改。若发生变化，应从最新日志重做上表修正，不能直接提交旧请求体。
- 本次接口没有提供乐观版本冲突检查，维护窗口内完成备份、核对和提交。

<a id="rerun-submit"></a>

#### 5.3 提交下游重跑

```powershell
curl.exe --fail-with-body -sS -X POST "$base/agents/rerun" `
  -H "Authorization: Bearer $env:RAGFLOW_TOKEN" `
  -H 'Content-Type: application/json' `
  --data-binary '@docker/evidence/t4-rerun-request.json'
```

- 当前日志保存会去掉索引向量，应选择能在下游重新执行 Tokenizer 的节点；不要复用被剔除向量后的末端输出直接入库。请求成功只代表排队成功。该接口会先删除目标文档原 ES 数据再运行，不提供在线原子切换；
- 不得截取单个 chunk 作为 `chunks` 列表提交，否则其他 24 块会丢失。不要选择 Tokenizer 为起点：它已经是最后节点，不能因此重新执行 Compiler；也不要选择 Compiler 为起点期待它重算，因为选中节点本身会被跳过。

<a id="rerun-verify"></a>

#### 5.4 验收

1.  文档达到 `run=3/progress=1`，新操作日志无错误；确认摘要确实收到正文，不再是请用户提供文本的回复。
2.  普通块仍完整；本例未改切块边界，预期为 25 块。从新结果按精确正文定位新题注，**不要假定旧 chunk ID 继续有效**，Compiler 按正文、文档 ID 和块序号重算 ID。
3.  ES 中新题注块正文、全文分词、1024 维向量一致；检查 Graph 关联的 `source_chunk_ids` 均能解析到存在的普通块。
4.  回读文档 Graph：`GET /api/v1/datasets/{kb}/documents/{doc}/structure/graph`，确认新人物实体与关系正确；检查 `迪丽热巴` 和 `Dilraba Dilmurat` 是否仍存在于当前有效实体/关系/图谱 JSON。特别复核 `@我是娜扎` 的描述，不能仅按原目标 chunk ID 查依赖。
5.  图谱是模型重新生成的结果，实体数/关系数可能变化，不能用固定 38 条作为成功标准；必须核对内容，不仅看任务 100%。历史日志和原始 DOCX 仍出现旧名不等于当前索引修正失败。
6.  核查时 t4 没有库级图谱；如需要 Artifacts 下的知识库合并 Graph，再运行 `POST /api/v1/datasets/{kb}/index?type=structure_graph`，并用同 URL 的 GET 查询进度。它是独立的图谱合并任务，不是重新解析源文件；不能先做合并来替代文档 Compiler 的修正。

<a id="rerun-rollback"></a>

#### 5.5 失败与回退

- 重跑失败后，先停止/等待该文档任务彻底结束，避免 Worker 覆盖恢复数据。备份失败状态，清理该文档本轮新写入的 ES 行，再按备份 `_id` 恢复完整原行，连同对应 MySQL 文档/任务/运行日志状态、计数及数据集导航引用一致恢复；
- 只恢复旧题注 chunk 不能恢复原来的 63 条记录。若已经运行了库级合并任务，还要处理其派生结果。此流程不是跨 MySQL/ES/Redis 的事务，未验证的自动 SQL 回滚命令不应直接执行。

<a id="kibana"></a>

## 13. Kibana 查询正文、BM25、向量与图谱

以下查询以 2026-10-27 的 t4 快照为例。使用前核对索引、知识库 ID 和当前 chunk ID。使用 92 的 Kibana 或创建 Data view 属于生产维护。[验证记录](issue.md#kibana-inspection)

<a id="kibana-login"></a>

### 1. 登录和选择入口

- 地址：<http://192.168.88.92:5601>。
- 用户名：`elastic`；密码取 92 的 `/home/cdky/workspace/github/ragflow/docker/env/storage.env` 中 `ELASTIC_PASSWORD`，不是 Linux 登录密码。`kibana_system` 是服务内部连接账号，不用于人工登录。
- 精确查询使用 **Dev Tools → Console**。粘贴下面请求，把光标放在该请求内，点击运行按钮或按 Ctrl+Enter。这里的 GET/POST 查询均为读取，不会调用 Embedding/LLM。
- 表格浏览使用 **Discover**，参见 [Discover](#kibana-discover)。

本租户索引为 `ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee`。一个索引里有多个知识库，不能把租户索引当作 t4 独占数据库；通过 `kb_id` 区分。t4 的 KB ID 为 `3c845f96d1ac11f18715a9a4fa662e3a`。

<a id="kibana-mapping"></a>

### 2. 列索引、看字段定义

```http
GET _cat/indices/ragflow*?v

GET ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee/_mapping
```

重点字段：

| 字段 | 含义 |
|----|----|
| `content_with_weight` | 保存的正文；本部署 `index=false`，可显示，不能据此字段做全文匹配 |
| `content_ltks` / `content_sm_ltks` | 全文检索分词；ES analyzer 为 whitespace，接收 RAGFlow 已分词的文本 |
| `q_1024_vec` | 1024 维 dense_vector，`index=true`、cosine 相似度 |
| `doc_id` / `kb_id` | 所属文档/知识库，keyword 精确过滤 |
| `compile_kwd` | 编译产物标记，可用于排除普通 chunk 之外的行 |
| `source_chunk_ids` | 图谱记录引用的源 chunk ID |

<a id="kibana-chunks"></a>

### 3. 查看 t4 的普通 chunk

```http
GET ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee/_search
{
  "size": 100,
  "track_total_hits": true,
  "_source": {
    "includes": ["id", "doc_id", "kb_id", "doc_type_kwd", "chunk_order_int", "content_with_weight", "content_ltks", "content_sm_ltks", "img_id"]
  },
  "query": {
    "bool": {
      "filter": [{"term": {"kb_id": "3c845f96d1ac11f18715a9a4fa662e3a"}}],
      "must_not": [{"exists": {"field": "compile_kwd"}}]
    }
  },
  "sort": [{"chunk_order_int": "asc"}]
}
```

此前现场有 25 个普通块，另有 38 条图谱记录。查询未排除 `compile_kwd` 时看到更多行是正常情况。`size` 只控制本页条数，完整计数看 `hits.total.value`。

查看题注块全部字段（包含完整向量）：

```http
GET ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee/_doc/cbae5b080fb2ca3b
```

GET 按 ES `_id` 获取，不额外应用 KB 过滤；应核对返回的 `kb_id/doc_id`。该 ID 属于题注 `图1. 迪丽热巴` 的旧版本；若以后从流程下游重跑，ID 可能变化，应先用上面的列表重新定位。

<a id="kibana-terms"></a>

### 4. 查看 BM25 的词项和统计

BM25 没有独立可展开的“索引表”，也没有与查询无关的固定分数。先看 `_source.content_ltks/content_sm_ltks`，再看词项统计：

```http
GET ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee/_termvectors/cbae5b080fb2ca3b
{
  "fields": ["content_ltks", "content_sm_ltks"],
  "term_statistics": true,
  "field_statistics": true,
  "positions": false,
  "offsets": false,
  "payloads": false
}
```

- 在 `term_vectors.content_ltks.terms` 查看每个词：`term_freq` 是该文档词频，`doc_freq` 是包含该词的文档数，`ttf` 是总词频；`field_statistics` 返回字段统计。
- 统计具有分片范围限制，不是只针对 t4 的精确库内统计。接口也可按需从字段内容计算词项，不等于导出 Lucene 底层倒排索引文件。
- [官方说明（8.11）](https://www.elastic.co/guide/en/elasticsearch/reference/8.11/docs-termvectors.html)

<a id="kibana-explain"></a>

### 5. 看 BM25 查询得分和命中原因

以下使用现场分词中确实存在的 `您好`，便于观察完整评分解释；它是诊断示例，不是推荐的业务查询词。

```http
GET ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee/_explain/cbae5b080fb2ca3b
{
  "query": {
    "match": {"content_ltks": "您好"}
  }
}
```

- 返回 `matched` 和 `explanation`，向下展开可查看 BM25 的词频、逆文档频率及长度归一化等评分组成。评分随索引数据变化。
- [Explain 官方说明（8.11）](https://www.elastic.co/guide/en/elasticsearch/reference/8.11/search-explain.html)

查看 t4 里匹配该词的块及每条评分：

```http
GET ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee/_search
{
  "size": 10,
  "explain": true,
  "_source": ["id", "doc_id", "content_with_weight", "content_ltks"],
  "query": {
    "bool": {
      "filter": [{"term": {"kb_id": "3c845f96d1ac11f18715a9a4fa662e3a"}}],
      "must_not": [{"exists": {"field": "compile_kwd"}}],
      "must": [{"match": {"content_ltks": "您好"}}]
    }
  }
}
```

该字段是 whitespace analyzer，中文查询词应按 RAGFlow 的实际分词构造；直接输入完整姓名未命中，单凭这一点不能判定索引错误。此示例仅解释 ES 单字段全文查询，不包含 RAGFlow 的查询改写、多字段权重、向量融合或 Rerank，分数不等于最终页面综合评分。

<a id="kibana-vectors"></a>

### 6. 查看向量及图谱引用

只返回正文、标识与向量，减少无关字段：

```http
GET ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee/_doc/cbae5b080fb2ca3b?_source_includes=id,doc_id,kb_id,content_with_weight,q_1024_vec
```

- 展开 `_source.q_1024_vec` 可看到 1024 个浮点值。向量不是可还原为文字的解释字段；语义相似度要使用同一 Embedding 模型、相同维数生成查询向量再检索。查看数值本身不需要再次调用模型。
- 这里按 ES 8.11.3 的实际返回给出请求，无需添加新版本的 `exclude_vectors` 参数。

查询直接引用该题注块的图谱行：

```http
GET ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee/_search
{
  "size": 100,
  "_source": {"excludes": ["*_vec"]},
  "query": {
    "bool": {
      "filter": [
        {"term": {"kb_id": "3c845f96d1ac11f18715a9a4fa662e3a"}},
        {"term": {"source_chunk_ids": "cbae5b080fb2ca3b"}}
      ]
    }
  }
}
```

它只查直接引用：不会包含没有顶层 `source_chunk_ids` 的图谱汇总 JSON，也会漏掉只引用图片块但描述中出现旧名的实体。完整影响范围见 [t4 局部修正手册](#data-storage)。

<a id="kibana-discover"></a>

### 7. 在 Discover 中表格浏览

1.  打开 **Discover → Create data view**。
2.  名称自定，Index pattern 填精确索引名 `ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee`。
3.  Timestamp field 选择 **I don't want to use the time filter**，避免默认时间范围将旧块或没有时间字段的图谱记录过滤掉。Data view 只建立 Kibana 查看配置，不重新构建 ES 索引。[官方说明（8.11）](https://www.elastic.co/guide/en/kibana/8.11/data-views.html)
4.  KQL 输入：

```text
kb_id: "3c845f96d1ac11f18715a9a4fa662e3a" and not compile_kwd: *
```

5.  添加列：`id`、`doc_id`、`chunk_order_int`、`doc_type_kwd`、`content_with_weight`、`content_ltks`、`img_id`。查看图谱时去掉 `not compile_kwd: *`，增加 `knowledge_graph_kwd`、`name_kwd`、`source_chunk_ids`。
6.  点行左侧展开查看字段/JSON。向量长数组、精确 term statistics 和评分解释优先用 Console。

只需要查看时执行本页查询即可。若需改正文，使用 RAGFlow chunk 更新接口；在 Kibana 直接只改 `content_with_weight` 会留下旧分词和旧向量。

<a id="task-troubleshooting"></a>

## 14. 文档处理与 Graph 任务排查

默认在 91 的 Bash 运行。核对实际队列前缀与目标文档，先采集只读证据。历史故障和补丁见[排查记录](issue.md#pdf-progress)。

<a id="task-inspect"></a>

### 快速排查入口

```bash
ssh cdky@192.168.88.91
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh status app
curl -fsS http://192.168.88.91:9380/api/v1/system/healthz
bash docker.sh into app
# 以下在应用容器 /ragflow 内执行。
python /opt/ragflow-ops/inspect_task.py
DOC_ID=实际文档ID
umask 077
mkdir -p logs/evidence
python /opt/ragflow-ops/inspect_task.py --doc-id "$DOC_ID" \
  > "logs/evidence/task-${DOC_ID}-$(date +%Y%m%d-%H%M%S).json"
exit
```

- [inspect_task.py](../docker/scripts/inspect_task.py) 使用容器已有数据库凭据，以只读事务查询文档、任务、流程节点和知识库 Graph 任务，再读取 Redis 心跳、队列和轨迹 TTL。
- 它不提交任务、不消费队列、不调用模型、不输出模型密钥或完整流程提示词。报告包含文件名和任务日志，外发前检查敏感信息。

本部署端口绑定到 LAN IP；在 **91 宿主机**访问 `127.0.0.1:9380` 会失败，应使用上面的 LAN 地址。在容器内部才使用 `127.0.0.1:9380`。

间隔 1—5 分钟再次采集，比较任务日志、Worker 当前任务和底层解析日志。对于批处理，观察窗口需结合已知批次耗时，不能简单以“5 分钟百分比不变”判定失败。

<a id="task-stages"></a>

### 先确定停在哪个阶段

| 最新任务消息 | 所在阶段 | 优先检查 |
|----|----|----|
| 排队，尚无 `Task has been received` | 等待执行 | Worker 心跳、队列 lag、消费者配置 |
| 已接收，未出现 `File fetched` | 读取原文件 | MinIO 地址、权限、对象是否存在 |
| `Start to work on a PDF` / `Structured: ... pages` | Parser | 实际页数、OCR/表格日志、CPU/GPU、批次大小 |
| Chunker / Extractor 消息 | 分块、抽取 | 切片数量、图片解释与模型调用、任务异常 |
| `Start knowledge compilation` / `compile batch` | Compiler | 模型响应、限流、超时、批次完成数 |
| `Start embedding inference` | 向量化 | Embedding 服务、输入量、批量与维度 |
| `Start to index` | 索引写入 | ES 健康、磁盘水位、写入错误 |
| `Scanning doc_graph rows` / `Building dataset graph` | 数据集 Graph 聚合 | 单独的 `structure_graph` 任务及已完成文档范围 |

文档与任务要同时看：

- `run`：0 未开始、1 运行、2 取消、3 完成、4 失败、5 调度中，以本版本 `TaskStatus` 为准。
- `task.progress` 是执行器任务状态；`document.progress` 由任务汇总。`progress=-1` 表示失败。
- `document.update_date` 会随状态汇总周期更新，**不是解析仍在推进的充分证据**；应结合 `task.update_date`、日志时间和内容。
- `retry_count=1` 不等于已经失败重试一次：当前代码首次领取任务也会递增该字段。
- Graph 聚合任务可能使用虚拟 `doc_id=graph_raptor_x`，只按真实文档 ID 查 task 会漏掉它。当前 `graph` 入口把任务 ID 存在 `graphrag_task_id`，但实际任务类型是 `structure_graph`；显式结构入口使用 `structure_graph_task_id` / `structure_task_id`。脚本按这些知识库字段补查，不能只凭字段名称推断任务不存在。

手工核验时连接已确认的开发数据库，执行以下只读 SQL。历史目标 `92:3306/rag_flow` 属于生产，不能用于本次开发验证：

```sql
START TRANSACTION READ ONLY;
SELECT id, name, run, progress, chunk_num, pipeline_id,
       process_begin_at, process_duration, update_date, progress_msg
FROM document
WHERE id = '<实际文档ID>';

SELECT id, doc_id, task_type, progress, retry_count,
       begin_at, update_date, progress_msg
FROM task
WHERE doc_id = '<实际文档ID>'
ORDER BY create_time DESC;
ROLLBACK;
```

不要直接修改 progress/run 制造“完成”，也不要删除任务行、Redis stream 或原文件来解卡。

<a id="task-logs"></a>

### 日志与资源检查

<a id="worker-log"></a>

#### 找到当前执行器日志

```bash
ls -lt logs/task_executor*.log
bash docker.sh logs app --since 30m --tail 150 ragflow

# 从报告 workers.name 选择当前执行器，不要只看部署前的旧日志。
LOG=logs/实际执行器日志文件名
TASK_ID=实际任务ID

# 优先使用 rg；服务器未安装时，等价使用 grep。
if command -v rg >/dev/null; then
  rg -n -F "$TASK_ID" "$LOG"
  rg -n '^20[0-9-]+ .*(__images__|Best table orientation|chunk mode|ERROR|WARNING)' "$LOG" | tail -n 60
else
  grep -nF "$TASK_ID" "$LOG"
  grep -nE '^20[0-9-]+ .*(__images__|Best table orientation|chunk mode|ERROR|WARNING)' "$LOG" | tail -n 60
fi
tail -n 40 -F "$LOG"
# Ctrl+C 退出查看。
```

- 有些 DeepDOC 日志没有 task_id，同一个 Worker 也可能同时处理多个文档。需结合任务开始/结束时间、心跳 current_task_ids 和阶段判断归属；不能把任意一条日志都归到目标任务。
- 任务中的 `Structured` 消息可能仅写入数据库，而未出现在 Worker 文本日志。

搜索 ERROR 时限定日志行前缀，避免把提示词、文档正文中的 ERROR 字样误判为执行异常。先读取异常类型及前后上下文，再检查该任务是否继续推进或已完成。

<a id="worker-resources"></a>

#### 检查容器配额和真实消耗

```bash
docker stats --no-stream ragflow-app-ragflow-1
docker inspect --format \
  'OOM={{.State.OOMKilled}} Restarts={{.RestartCount}} Started={{.State.StartedAt}} NanoCpus={{.HostConfig.NanoCpus}}' \
  ragflow-app-ragflow-1
docker top ragflow-app-ragflow-1 -eo pid,ppid,pcpu,pmem,nlwp,etime,comm
free -h
vmstat 1 5
df -h / /home
```

Linux Docker 中约 800% 表示约 8 个 CPU 核的用量。宿主机总体 CPU 空闲不代表容器没有触及自身配额。

本环境为 cgroup v2，可连续采集：

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh into app
python - <<'PY'
import time
from pathlib import Path
for i in range(2):
    print('sample', i)
    for name in ('cpu.max', 'cpu.stat', 'memory.current', 'memory.max', 'memory.events'):
        path = Path('/sys/fs/cgroup') / name
        print(name, path.read_text().strip() if path.exists() else 'not available')
    if i == 0:
        time.sleep(5)
PY
exit
```

- `cpu.max=800000 100000` 表示 8 核配额。比较两次 `nr_throttled` 与 `nr_periods` 增量；两者接近说明多数调度周期触及限额。`throttled_usec` 可累计多个线程的等待，不能直接当作任务剩余时间。
- `memory.events` 中 oom/oom_kill 非零时，结合容器启动时间和日志排查内存问题。

<a id="pdf-pages"></a>

#### 核验 PDF 页数

下面使用本部署的 MinIO 配置和 `DOC_ID` 读取原文件，仅统计页数，不触发 OCR 或模型请求。文件会读入容器内存，大文件应先检查剩余内存。

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh into app
export DOC_ID=实际文档ID
python - <<'PY'
import os
import pymysql
import pypdfium2
from minio import Minio
e = os.environ
c = pymysql.connect(host=e['MYSQL_HOST'], port=int(e['MYSQL_PORT']),
                    user=e['MYSQL_USER'], password=e['MYSQL_PASSWORD'],
                    database=e['MYSQL_DBNAME'])
try:
    with c.cursor() as q:
        q.execute('START TRANSACTION READ ONLY')
        q.execute('SELECT kb_id,location FROM document WHERE id=%s', (e['DOC_ID'],))
        row = q.fetchone()
        if not row:
            raise SystemExit('Document not found')
finally:
    c.rollback()
    c.close()
m = Minio(e['MINIO_HOST'] + ':9000', access_key=e['MINIO_USER'],
          secret_key=e['MINIO_PASSWORD'], secure=False)
response = m.get_object(row[0], row[1])
try:
    data = response.read()
finally:
    response.close()
    response.release_conn()
pdf = pypdfium2.PdfDocument(data)
try:
    print('bytes:', len(data), 'pages:', len(pdf))
finally:
    pdf.close()
PY
exit
```

<a id="task-queues"></a>

### 队列、缓存和存储检查

<a id="redis-diagnostics"></a>

#### Redis：区分待领取、执行中和记录过期

查看诊断报告中的 `workers`、`queues`、`pipeline_log_ttl`：

- `lag` 表示尚未投递给消费者的条目；`pending` 是已投递但尚未 ACK 的条目，正常长任务也会 pending。
- 心跳新、目标任务在 `current_task_ids`、底层日志增加：优先判断执行缓慢。
- 心跳过期、任务长期 pending：核查执行器进程和异常退出，不能仅凭 pending 数量强行 ACK。
- `pending_sample` 只读展示各队列最前面的至多 10 条 pending；`known_task_progress=1` 仍 pending 时，检查操作日志和 ACK 收尾。样本中没有目标消息不代表整个队列没有它。
- TTL 正数为剩余秒数，`-2` 为 key 不存在，`-1` 为没有过期时间。缺失轨迹不等于任务被删除。
- `expired_keys` 是实例累计值，不能单独证明某个 key 过期；应结合目标 TTL、源码设置和回调间隔。
- 既有部署记录使用 Redis **DB 1**。历史 91 解析队列前缀为 `te.dev91`，92 为 `te`，完整 Stream 名为 `<前缀>.<优先级>.common`。
    - 当前 `inspect_task.py` 的 `queues` 字段只检查 `te.0.common/te.1.common`，会遗漏开发队列。
    - 先从容器配置确认实际前缀，再对两个优先级执行 `XINFO GROUPS <stream>` 和 `XPENDING <stream> rag_flow_svr_task_broker`；队列名不能固定照抄历史 `te.dev91`。

<a id="task-storage"></a>

#### 存储服务

以下为存储维护人员在 92 使用的只读命令。日常开发先从 91 检查应用健康和依赖连接。

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh status storage
bash docker.sh logs storage --since 30m --tail 100 mysql redis elasticsearch minio
df -h / /home
```

- 结合 91 的 `/api/v1/system/healthz` 检查跨机访问。MinIO 只验证服务存活还不够，必要时在 Console 核对目标对象存在、大小和下载能力；ES 写入异常则在 Kibana 检查集群、索引与磁盘水位。
- 具体连接、鉴权命令见 [容器内连接](#inside)，不要将 app.env/storage.env 的内容粘贴到工单。

<a id="task-recovery"></a>

### 按原因选择处理方式

| 确认的原因 | 处理方式 | 验证重点 |
|----|----|----|
| 有新页数/表格日志，CPU 忙 | 保留当前任务运行；减少同时提交的大 PDF | 后续出现下一批 Structured、Compiler 和 Indexer 消息 |
| CPU 持续被配额限制 | 评估同机旧服务占用后，在维护窗口调整新应用配额或拆分 Worker | 处理耗时、throttling、旧服务响应；不要直接重启整个 Docker |
| 大量正向表格仍做四方向 OCR | 用代表性小样本评估 `TABLE_AUTO_ROTATE=false` | 方向、单元格对应、图谱质量；含旋转表格时不能盲目关闭 |
| 批次回调超过 30 分钟 | 小样本评估减小 `PDF_PARSER_PAGE_BATCH_SIZE`；代码层修正进度状态保存 | 回调间隔、跨页表格/段落质量、过期后进度恢复 |
| CPU 解析长期不满足吞吐 | 评估 GPU DeepDOC 或其他已配置解析器；纯文字 PDF 可评估纯文本模式 | 解析完整性、表格和图片信息是否丢失、部署成本 |
| Compiler/Embedding 的 401/403 | 核对所选模型实例及授权 | 应用实际调用成功，不能只看模型列表可访问 |
| 模型 429/超时/5xx | 检查服务商配额、延迟与并发，依据错误控制重试 | 批次持续完成、费用及重复处理量 |
| Worker 退出/OOM | 保存证据，修复资源问题，再按 UI 支持的流程重试目标文档 | 新任务被领取、旧执行不再并行、没有重复索引 |
| ES/MinIO/Redis 持续错误 | 先恢复对应依赖，再决定任务重试 | 从应用容器验证读写路径与任务阶段 |
| Graph 100% 但仍 pending、缺操作日志 | 检查任务类型校验及 finally 到 ACK 的异常路径，修复后制定单任务恢复步骤 | 图谱结果、操作日志、队列确认三者一致 |

仅在任务确实失败或业务决定中止时，通过界面取消并确认执行结束后重试。DeepDOC 批内缺少回调，取消可能不会立即生效。不要并行启动相同大文件的重复任务，也不要把重启作为第一步。

- 环境参数需进入新应用容器才生效，修改文件不会改变正在执行的 Parser；`docker compose restart` 也不会加载新的容器环境。调整后通常需要重建新应用容器，会中断当前工作，安排在任务结束后的维护窗口，具体命令见[部署操作](#deploy)。
- 资源上限可以在线更新，代码切换仍需重建进程。

当前实现将运行中节点的数字进度保存在 Pipeline 实例，Redis 仅保留 UI 轨迹，并增加批内回调；任务进程重启后仍需依照现有任务重试机制重新执行。

<a id="task-verify"></a>

### 恢复验收与证据归档

1.  重新运行 `inspect_task.py --doc-id`，确认文档 `run=3`、`progress=1`，关联解析任务完成，日志包含最终写入成功。
2.  检查切片数量及抽样内容，尤其是表格、图片、跨页段落；状态完成不等于解析质量合格。
3.  检查 Compiler 成功记录及 Graph 中的来源文档。已有数据集 Graph 可能是在第二个文件完成前生成，需要根据界面支持的操作重新生成并核验覆盖范围。
4.  检查后续查询/检索能命中目标文档；如做模型效果测试，记录模型、参数、耗时和费用。
5.  保存故障前后诊断 JSON、关键日志时间段、版本、配置变更及验证结果；将排查、修复、验证和回退步骤记录到 [issue.md](issue.md)。

<a id="empty-graph"></a>

### 空 Graph 的检查顺序

1.  用 `inspect_task.py --doc-id` 核对文档自身的 `pipeline_id` 和任务类型。修改知识库的默认流程不会自动更新已有文档的绑定。
2.  核对运行 DSL 中 VLM、Extractor、Compiler、Embedding 的模型和输入变量，检查错误码及各节点输出。图片对象已写入或文档进度为 100% 时，仍需检查图片描述、摘要及 Compiler 实际产物。
3.  从 ES 按 `kb_id/doc_id` 核对文档级实体、关系及模板 ID。日志为 `No doc_graph rows found.` 时，先恢复文档编译结果，再生成知识库级 Graph。
4.  涉及重新绑定文档和解析时，先备份原文件、运行 DSL 和索引。重建后检查正文、图谱来源、完成时间和队列状态。相关实例见 [local 空 Graph](issue.md#local-empty-graph) 和 [t1/t2 排查](issue.md#t1-t2-graph)。

<a id="graph-finalize"></a>

### Graph 已完成但未 ACK 的单消息恢复

只处理已有结果的单个 `structure_graph` 成功任务。先确认 `task.progress=1`、近期 Worker 的 current 不再包含该任务、ES 有对应数据集实体/关系记录，并备份 MySQL。不要将以下办法用于仍运行、失败或没有索引结果的任务。

- 工具 `docker/scripts/finalize_graph.py` 默认只检查；`--apply` 才补日志并 ACK。它校验任务类型、任务进度、数据集引用、参与文档、近期执行器、ES 索引以及成功日志；只确认指定消息。
- 传入一个新的私有 `--backup` 路径保存队列原文和任务信息，已有同名文件时拒绝覆盖。操作日志用数据集、类型和任务开始时间定位；不要并发运行恢复命令。

当前工具只接受 `te.0.common` 和 `te.1.common`，不能处理 91 的 `te.dev91.*.common` 队列。以下步骤仅供批准的存储维护使用，按实际 Stream 选择 `--queue`。

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh into app
TASK_ID=待恢复的任务ID
DATASET_ID=对应知识库ID
MESSAGE_ID=该任务的精确Redis消息ID
QUEUE=te.0.common  # 按盘点选择实际 Stream
# 只检查：输出应确认 progress=1、有 dataset_graph_rows
python /opt/ragflow-ops/finalize_graph.py \
  --task-id "$TASK_ID" --dataset-id "$DATASET_ID" --message-id "$MESSAGE_ID" --queue "$QUEUE"
# 核对 MySQL 备份后再执行单消息恢复
# /ragflow/logs 为宿主持久化目录；恢复证据按 600 权限保存
python /opt/ragflow-ops/finalize_graph.py \
  --task-id "$TASK_ID" --dataset-id "$DATASET_ID" --message-id "$MESSAGE_ID" --queue "$QUEUE" \
  --apply --backup "/ragflow/logs/graph-recovery-${TASK_ID}-$(date +%s).json"
exit
```

任何检查失败都先停止恢复并调查，不用 SQL 强改 `progress=1` 绕过检查。ACK 成功后再次运行只读检查，应 `pending=false`、`operation_logs=1`；再核对 KB 完成时间及界面 Graph 内容。

<a id="knowledgebase-cleanup"></a>

## 15. 旧知识库残留数据清理

本节记录 2026-10-26 只读盘点后拟定的停机清理方案，停机、备份、删除和重启均未执行。目标是清除核准范围内的旧知识库及其派生数据，保留账号、租户、模型、流程和系统配置。

**仅供单独批准的生产维护。** 下列命令涉及 92 共享存储及两端停写，开发期间不得执行。示例 ID、对象数量及保留项只对应当时的盘点，执行前须重新核准范围。

<a id="cleanup-scope"></a>

### 1. 历史盘点与清理范围

| 项目                | 实际位置                                           |
|---------------------|----------------------------------------------------|
| 新应用              | `192.168.88.91:8088`；容器 `ragflow-app-ragflow-1` |
| 应用镜像            | `ragflow-local:v0.27.2-progress-20261023`          |
| MySQL               | `192.168.88.92:3306`，库 `rag_flow`                |
| Elasticsearch       | `192.168.88.92:9200`                               |
| MinIO API / Console | `192.168.88.92:9000` / `:9001`                     |
| Redis               | `192.168.88.92:6379`，逻辑库 **DB 1**              |
| 两台服务器项目目录  | `/home/cdky/workspace/github/ragflow`              |
| 运维目录            | 项目下 `docker`                                    |

91 上同时运行旧实例 `ragflow-server`，网页端口 `8890`，且有旧 MySQL、MinIO、Redis、ES。**本文不操作旧实例，不使用 91 的 9000/9001/9200 等旧存储端口。**

执行前在停写状态重做盘点。下表为历史记录。

| 数据位置 | 2026-10-26 盘点结果 | 当时拟定处理 |
|----|----|----|
| MySQL `knowledgebase` / `document` / `file2document` | 均为 0 行 | 已清空，复核即可 |
| MySQL `task` | 3 行，均为已完成的 `structure_graph`，`doc_id=graph_raptor_x` | 删除本文列出的 3 个任务 |
| MySQL `pipeline_operation_log` | 7 行，均属于下述两个旧知识库 | 按两个 KB ID 删除 |
| MySQL `connector` / `connector2kb` / `sync_logs` | 均为 0 行 | 保持为空；避免数据源自动重新导入 |
| MySQL `file_commit` / `file_commit_item` | 均为 0 行 | 无版本内容需要追加清理 |
| MySQL `file` | 4 个目录：两个 `/`、`.knowledgebase`、`skills`；没有文件 | 保留，不能把这些基础目录当成孤儿文件 |
| MySQL `user_canvas` / `user_canvas_version` | 2 个解析流程 / 20 个版本 | 保留；未检出 `imagetemps` 文本引用 |
| MySQL `dialog` / `conversation` / `api_4_conversation` / `memory` | 均为 0 行 | 无会话、记忆内容需要追加清理 |
| ES `ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee` | `_count=344` | 删除该旧业务索引 |
| ES `ragflow_doc_meta_514a9b36ce8511f18a4cdf41f1d8e4ee` | 0 条 | 可一并删除，后续按需创建 |
| MinIO `5ef3b38ecea911f18a4cdf41f1d8e4ee` | 1 个对象，698,289 字节 | 删除对象及该旧 KB 桶 |
| MinIO `f98bec50ce8f11f18a4cdf41f1d8e4ee` | 1 个对象，698,289 字节 | 删除对象及该旧 KB 桶 |
| MinIO `imagetemps` | 4,193 个对象，175,079,836 字节，约 167 MiB | 清空旧解析图片，保留空桶 |
| MinIO `223d22face8511f18a4cdf41f1d8e4ee` | 空桶，与一个用户根目录 ID 一致 | 保留 |
| Redis DB 1 | 盘点时 19 个 key；两条 Stream 的 pending/lag 均为 0 | 清理旧任务、解析状态和流程运行缓存；保留计数器 |

两个旧知识库 ID：

```text
5ef3b38ecea911f18a4cdf41f1d8e4ee
f98bec50ce8f11f18a4cdf41f1d8e4ee
```

ES 的 344 条记录均属于上述两个 KB：339 条 `hypergraph` 图谱记录（156 个实体、183 个关系）和 5 条 `doc_deleted` 标记。不是单纯的空索引残留。

<a id="cleanup-causes"></a>

### 2. 为什么页面删除后仍有数据

历史记录曾确认删除路径的现场源码与当时本地 SHA-256 一致。本次只检查当前本地实现，不能把旧现场哈希当成当前部署一致性证明：

- `api/apps/services/dataset_api_service.py::_delete_datasets_sync` 当前会取消同步任务、删除连接器关联、清理文档及残留关系；仍不是跨 MySQL/ES/MinIO/Redis 的统一事务。
- `api/db/services/document_service.py::remove_document` 当前还清理导航引用、记录删除标记，并按引用处理 Wiki/Artifact 等产物。部分异常只记日志，不能据此认定 KB 桶和共享 `imagetemps` 已完整清空。
- `common/doc_store/es_conn_base.py::delete_idx` 在传入 KB ID 时直接返回，因为同租户的多个 KB 共用一个 ES 索引。知识库级图谱和删除标记不能仅靠文档 ID 删除来全部覆盖。
- `rag/utils/base64_image.py::image2id` 默认桶为 `imagetemps`；解析流程存在使用该默认桶的调用。它是共享存储位置，不能仅凭名称认定所有对象都可以删。

因此，要同时处理关系数据、检索数据、对象和任务状态。**空桶、空索引、基础目录存在本身不影响从头构建。**

<a id="cleanup-backup"></a>

### 3. 暂停写入并完成备份

以下均为服务器上的 **Bash** 命令。不要在本地 PowerShell 原样运行。数据库凭据从现有容器环境获取，不把 SSH 密码当作数据库密码。

先停止页面操作、SDK 上传和流程调试。当前 API、Task Executor、Data Sync 均由新应用容器承载；如以后新增了外置 Worker/定时导入任务，也必须一起停止。

**在 91 执行：**

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh stop app
bash docker.sh status app
# 92 也连接相同存储；在 92 同样停止 app，再进行备份和数据清理。
```

确认新应用容器停止。保留旧实例运行。

保存应用配置和部署标识，备份目录权限限制为当前用户：

```bash
umask 077
APP_BACKUP="backups/pre-kb-cleanup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$APP_BACKUP"
cp -p env/app.env compose/compose.app.yml config/service_conf.yaml.template "$APP_BACKUP/"
git rev-parse HEAD > "$APP_BACKUP/source-revision.txt"
docker inspect --format '{{.Config.Image}} {{.Image}}' ragflow-app-ragflow-1 > "$APP_BACKUP/app-image.txt"
```

**在 92 执行：**

先对 ES 做受支持的 snapshot 备份；现有部署已配置 `ragflow_backup` 仓库。如果请求失败，先排查仓库，不继续删除。

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh into storage elasticsearch
snapshot="pre-kb-cleanup-$(date +%Y%m%d-%H%M%S)"
  curl -fsS -u "elastic:$ELASTIC_PASSWORD" -X PUT \
    "http://localhost:9200/_snapshot/ragflow_backup/$snapshot?wait_for_completion=true"
exit
```

确认返回的快照状态为 `SUCCESS`，再运行现有整套冷备份脚本：

```bash
cd /home/cdky/workspace/github/ragflow/docker
APP_STOPPED=1 APP_URLS="http://192.168.88.91:9380 http://192.168.88.92:9380" bash scripts/backup.sh
```

脚本会停止并重新启动 **92 上本次部署的存储服务**，归档七个卷、校验 gzip 并生成 `SHA256SUMS`。记录实际输出的备份目录；应用仍应保持停止。将 91 的配置备份与这次存储备份关联保存，最好另存一份到其他磁盘/主机。已有备份会保留旧数据，这是恢复用途，不代表活动数据未清理。

<a id="cleanup-mysql"></a>

### 4. 停机后复核并清理 MySQL

在 92 打开新实例的 MySQL 交互终端：

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh into storage mysql
MYSQL_PWD="$MYSQL_PASSWORD" mysql -u ragflow -D rag_flow
exit
```

先执行只读 SQL，复核与[已核准的清理范围](#cleanup-scope)一致：

```sql
SELECT COUNT(*) AS kb_count FROM knowledgebase;
SELECT COUNT(*) AS doc_count FROM document;
SELECT COUNT(*) AS file_link_count FROM file2document;
SELECT id, doc_id, task_type, progress FROM task;
SELECT kb_id, task_type, COUNT(*) FROM pipeline_operation_log GROUP BY kb_id, task_type;
SELECT id, name, type, source_type FROM file;
SELECT COUNT(*) AS memory_count FROM memory;
SELECT COUNT(*) AS connector_link_count FROM connector2kb;
SELECT COUNT(*) AS sync_log_count FROM sync_logs;
```

**若出现新知识库、文件、任务或新的使用方，不继续套用本次清单。** 对仍存在的 KB，应先经正常页面/API 删除，记录其 KB ID、文档 ID、对象位置，再停机清理残留。已有知识库被删后，不能再指望调用一次删除 API 自动找回全部孤儿数据。

历史方案拟执行以下定向删除，不删 `file`、账号、模型、流程表：

```sql
START TRANSACTION;

DELETE FROM task
WHERE task_type = 'structure_graph'
  AND doc_id = 'graph_raptor_x'
  AND id IN (
    '3f2af8facf5811f184dc27e9a0ee1736',
    '518db9a4cebf11f184dc27e9a0ee1736',
    '5f5ddfe2cea511f18a4cdf41f1d8e4ee'
  );
SELECT ROW_COUNT() AS deleted_tasks;

DELETE FROM pipeline_operation_log
WHERE kb_id IN (
  '5ef3b38ecea911f18a4cdf41f1d8e4ee',
  'f98bec50ce8f11f18a4cdf41f1d8e4ee'
);
SELECT ROW_COUNT() AS deleted_logs;

SELECT COUNT(*) AS remaining_tasks FROM task;
SELECT COUNT(*) AS remaining_logs FROM pipeline_operation_log;
```

首次执行预期删除 3 个任务、7 条日志，剩余均为 0。检查符合预期后执行 `COMMIT;`；异常则执行 `ROLLBACK;` 并停止后续步骤。不要将“任务的 doc_id 不在 document 中”当成通用删除规则，结构化任务本来就可能使用占位 doc_id。

后续如果盘点发现文件版本/知识库编译历史，还需按 KB/文件夹归属处理 `file_commit_item`、`file_commit` 及其对象内容；如果发现连接器，则解绑 `connector2kb` 并清理对应同步任务。历史盘点时这些表没有相关数据；当前必须按目标归属重新检查，不做全表清空。

<a id="cleanup-es"></a>

### 5. 清理 Elasticsearch

历史盘点时所有 KB 均已删除。仅当确认精确索引内全部数据均属于批准删除的范围，且没有其他知识库共用时，才允许整索引删除。不要删除 `.kibana*`、`.security*`、`.internal*` 等系统索引，也不要使用全索引删除。

在 92 先核对索引：

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh into storage elasticsearch
curl -fsS -u "elastic:$ELASTIC_PASSWORD" \
    "http://localhost:9200/_cat/indices/ragflow*?v&h=index,docs.count,store.size"
exit
```

核对后执行：

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh into storage elasticsearch
(
  set -e
  for index in \
    ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee \
    ragflow_doc_meta_514a9b36ce8511f18a4cdf41f1d8e4ee
  do
    curl -fsS -u "elastic:$ELASTIC_PASSWORD" -X DELETE "http://localhost:9200/$index"
  done
)
exit
```

每个请求应返回 `acknowledged: true`。如果以后仅删除某个 KB，而租户仍有其他 KB，就必须按 `kb_id` 对业务索引进行定向删除，不能删整个租户索引。编译历史还可能使用 KB ID 命名的独立索引，需结合实际清单识别，不能只检查一个预设索引。

<a id="cleanup-minio"></a>

### 6. 清理 MinIO

本次使用 **92 的 MinIO 容器内置 `mc`**；92 宿主机未安装 `mc`。先创建只指向该容器本机的别名：

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh into storage minio
mc alias set kbcleanup http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
  mc ls kbcleanup
exit
```

先预览删除范围，`--dry-run` 不删除对象：

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh into storage minio
for bucket in 5ef3b38ecea911f18a4cdf41f1d8e4ee f98bec50ce8f11f18a4cdf41f1d8e4ee imagetemps
  do
    mc rm --dry-run --recursive --force --versions "kbcleanup/$bucket/"
  done
exit
```

复核这三个桶内的对象和未完成上传均在删除范围，尤其确认共享 `imagetemps` 没有待保留的对象，再执行：

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh into storage minio
(
  set -e
  for bucket in 5ef3b38ecea911f18a4cdf41f1d8e4ee f98bec50ce8f11f18a4cdf41f1d8e4ee imagetemps
  do
    mc rm --recursive --force --versions "kbcleanup/$bucket/"
    mc rm --incomplete --recursive --force "kbcleanup/$bucket/"
  done
  mc rb kbcleanup/5ef3b38ecea911f18a4cdf41f1d8e4ee
  mc rb kbcleanup/f98bec50ce8f11f18a4cdf41f1d8e4ee
  mc ls kbcleanup
  mc ls --recursive --versions kbcleanup/imagetemps
)
exit
```

这三个桶盘点时均未开启版本控制；命令仍覆盖对象版本及未完成上传，以免只清掉当前可见对象。不要绕过对象锁/保留策略；若删除报错，检查错误原因后再继续。

`imagetemps` 是共享桶。仅在全部关联任务已停、桶内对象均在批准范围且无保留引用时才能清空。部分清理按核准的对象键执行。

保留 `imagetemps` 空桶和用户根目录空桶是正常结果。不要删除全部 UUID 桶：某些桶对应用户目录、工作区或其他有效文件。不要直接删除 Docker 卷里的 MinIO 内部文件。

<a id="cleanup-redis"></a>

### 7. 清理 Redis 的旧任务与运行缓存

只处理 **92 的 DB 1**。历史盘点时没有在途任务、会话或 Memory 数据，但存在 `id_generator:memory` 计数器，保留它。这里不使用 `FLUSHALL`，也不要求清空整个 DB。

在 92 用 SCAN 盘点候选 key，核对其归属、业务用途和待确认任务。

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh into storage redis
export REDISCLI_AUTH="$REDIS_PASSWORD"
  for pattern in "doc:chunking_*" "canvas:replica:*" "*-cancel" "*-logs" "te.*.common" "task_executor_*" "TASKEXE"
  do
    redis-cli -n 1 --scan --pattern "$pattern"
  done
exit
```

上述模式用于筛选候选项。`te.*.common` 同时匹配开发和生产队列，须分别核对；删除只使用核准的精确 key 清单。`canvas:replica:*` 是运行/调试副本，删除后丢弃旧调试状态；保存在 MySQL 的解析流程定义和版本仍保留。

将审核通过的精确 key 每行一个写入容器内的 `/tmp/kb-cleanup-approved-keys.txt`，再执行：

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh into storage redis
export REDISCLI_AUTH="$REDIS_PASSWORD"
(
  set -e
  while IFS= read -r key || [ -n "$key" ]; do
    if [ -n "$key" ]; then
      redis-cli -e -n 1 UNLINK "$key"
    fi
  done < /tmp/kb-cleanup-approved-keys.txt
  redis-cli -e -n 1 --scan
)
exit
```

若仍有旧解析缓存，应核对其来源后追加精确 key，不能为了让 `DBSIZE=0` 而删计数器或其他系统状态。历史盘点中两个 Stream 没有 pending，9 条消息已经消费；这不代表历史流记录会自动消失。

<a id="cleanup-verify"></a>

### 8. 验收与恢复服务

在停写状态按核准范围验收。下列数量及空表预期对应历史全量清理方案。

- MySQL：`knowledgebase`、`document`、`file2document`、`task`、`pipeline_operation_log` 都为 0；连接器关联、同步日志及文件版本表无旧 KB 记录。
- ES：两个指定旧业务索引不存在；系统索引仍保留。
- MinIO：两个旧 KB 桶不存在；`imagetemps` 没有对象、旧版本和未完成上传；用户根目录空桶仍在。
- Redis：旧解析任务流、状态、调试副本已清除；允许保留计数器。
- 保留项：2 个账号/租户、4 个基础目录、2 个解析流程及 20 个流程版本；模型供应商/模型实例/分组配置和 API 凭据未改动。

检查 92 存储健康后，按维护前记录恢复原先运行的应用。以下以 91 应用为例，若维护前 92 应用也在运行，由生产维护人员恢复并验收。

```bash
# 92
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh status storage
```

```bash
# 91
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh start app
bash docker.sh status app
curl -fsS http://192.168.88.91:9380/api/v1/system/healthz
```

应用刚启动可能尚未就绪，等待健康检查通过再进入 `http://192.168.88.91:8088`。刷新页面，确认知识库列表为空，解析流程和模型配置仍可用。Worker 重建空队列、心跳 key 属正常现象，不代表旧业务数据恢复。

生产维护验收仅使用该次授权范围内的探针；开发复现必须在隔离存储中。新建小型测试 KB，上传小文档，验证解析、分块、检索和图片显示。新桶、新索引、新 `imagetemps` 对象都会按需出现。删除测试 KB 后按新 ID 再检查残留；当前删除路径仍不是跨存储事务，因此要按新 ID 复查残留。

原有对话助手、搜索配置、Agent 或数据源若引用旧 KB ID，需改绑新 ID；同名重建 KB 不会复用旧 ID。恢复后检查保留的流程配置和会话引用。应用日志和运维备份不影响新 KB 建库；如目标还包括敏感内容彻底销毁，应另行确定日志、快照、备份的保留范围，不能与本次活动数据清理混为一谈。

<a id="cleanup-rollback"></a>

### 9. 失败处理与恢复

- 任一删除步骤失败，保持新应用停止，保存错误及已完成步骤，先核查再继续。若要回滚，使用[停写后取得的](#cleanup-backup)同一时间点备份成套恢复 MySQL、ES、MinIO、Redis；ES 优先使用已验证成功的 snapshot。
- 不要只回滚 MySQL 后继续服务，否则索引和对象可能仍然缺失。参见[备份与恢复](#backup)，目标仅限 `ragflow-storage` 的卷和服务。

