# DataFactory 开发指导

DataFactory 是部署在 RAGFlow 旁边的训练数据制作平台。它把 RAGFlow 中已解析、已编码的知识库加工成微调训练数据：首期支持 Embedding 模型（文本与多模态），后续支持 Reranker 与 LLM（SFT / 偏好）。产品与架构基线见 [design/PRODUCT_DESIGN.md](design/PRODUCT_DESIGN.md)；修改其中描述的行为前，先阅读对应章节。设计文档与代码不一致时以代码为准，并在同一次改动中修正设计文档。

仓库根目录 [CLAUDE.md](../CLAUDE.md) 继续适用（核心立场、工作规则、files 文档维护、91/92 规则）。本文件只补充 `datafactory/` 特有的规则。`datafactory/web/` 下的前端工作还须遵循 [web/CLAUDE.md](web/CLAUDE.md)。

## 核心立场

- 将遗留代码视为负债，而不是需要兼容的目标。优先删除，而不是垫片（shim）、已弃用分支、包装 API 和双轨迁移。
- 每种行为只保留一条实现路径。新方案替代旧方案时，在同一次改动中删除旧方案。
- 代码、注释和文档中不保留被注释掉的代码、"以后再迁移"的备注或兼容性表述。
- 缩小公开接口：模块私有辅助函数以 `_` 开头；包只导出其他包实际使用的内容。
- 重构围绕所属抽象展开（引擎、事实层、适配器），而不是围绕相邻的胶水代码。
- `files/issue.md` 中记录的一期/二期制作服务已不在当前代码中。不要恢复它们的文件、接口、SQLite 存储或页面路由；只按设计文档 §3.4 吸收其经验。

## 系统边界（不可违反）

RAGFlow 是知识平面，DataFactory 是生产平面（设计文档 §4）。

1. DataFactory 不导入 RAGFlow 的任何 Python 模块（`api`、`rag`、`common`、`deepdoc`、`agent`、`memory`），也不连接 RAGFlow 的 MySQL、Doc Store（ES/Infinity/…）、Redis 键或对象存储桶。所有访问都经 Corpus Gateway 的 HTTP 接口。
2. Gateway 对语料与检索只读，另外提供模型调用。不要新增写入 RAGFlow 的接口。回写（如把合成问题写入 `question_kwd`）需要单独设计评审（ADR-08）。
3. 模型凭据保留在 RAGFlow。DataFactory 只保存 `model_id` 引用。不得新增 API Key 字段、厂商 SDK 客户端或直接调用模型厂商的代码。
4. DataFactory 内不做解析、切片、OCR，也不重新编码语料。语料有问题时在 RAGFlow 修复，再新建快照。DataFactory 只编码自己生成的内容（查询、回答）。
5. 快照冻结内容（段的 parts + 资产字节），不冻结向量。RAGFlow 切片 ID 是内容寻址的（`xxhash64(content + doc_id)`），重解析后会变化；不要在记录它的快照之外依赖切片 ID。
6. RAGFlow 存储的向量是"检索视角"向量（混合标题向量，有 `question_kwd` 时编码的是问题而非正文）。只用于候选召回和语义成束。教师分数、去重相似度、质量指标来自 Reranker 或新编码，并必须记录 `model_fingerprint`。

### Gateway 的归属

Gateway 位于 RAGFlow 内，不在本目录：

- `api/apps/restful_apis/gateway_api.py`：路由，自动注册到 `/api/v1/gateway/`。
- `api/apps/services/gateway_service.py`：组合 `Dealer.chunk_list / fetch_chunk_vectors / retrieval`、`MatchDenseExpr` + `settings.docStoreConn.search`、`LLMBundle`、`KnowledgebaseService.accessible`、`tenant_model_service`、`settings.STORAGE_IMPL`。
- 测试位于 `test/unit_test/api/`。

Gateway 的改动遵循根目录 CLAUDE.md 中关于 RAGFlow 代码的规则。保持精简：RAGFlow 中不得出现 DataFactory 的业务概念（配方、样本、发布）。Gateway 需要的逻辑若只存在于 RAGFlow 的私有辅助函数中，应在其所属模块内将其收敛为公开函数，而不是复制。契约版本由响应头 `X-Gateway-Version` 标识；任何破坏性变更都要升版本，并在同一次改动中更新 `backend/src/datafactory/gateway/`，不做多版本并存。

## 目录结构

```
datafactory/
├─ CLAUDE.md                     本文件
├─ design/PRODUCT_DESIGN.md      产品与架构基线
├─ backend/
│  ├─ pyproject.toml             独立包 `datafactory`（uv）
│  ├─ src/datafactory/
│  │  ├─ app/                    FastAPI 应用工厂、路由（/api/factory/v1）、依赖注入、SSE
│  │  ├─ core/                   配置、环境守卫、ID（ULID）、错误、日志、幂等
│  │  ├─ gateway/                唯一的 RAGFlow 客户端：类型化 DTO + HTTP 客户端 + NDJSON 流读取
│  │  ├─ domain/                 Pydantic 领域模型：ContentPart、Asset、Segment、Query、Judgment、Generation、Conversation、Sample 视图
│  │  ├─ store/                  SQLAlchemy 模型、仓储、Alembic 迁移、对象存储（MinIO）、Parquet 读写
│  │  ├─ corpus/                 快照构建、体检报告、文档家族/近重复、过期检测
│  │  ├─ engine/                 配方 Schema、DAG 解析、执行器、缓存、预算、模型客户端、AIMD 并发、预览
│  │  │  └─ columns/             每种列类型一个模块
│  │  ├─ tasks/                  任务视图：retrieval、rerank、chat_sft、preference（含各自门禁）
│  │  ├─ quality/                评审量表接入、门禁评估、指标
│  │  ├─ review/                 审核队列、修订、分配
│  │  ├─ release/                冻结、清单、差异、报告
│  │  ├─ adapters/               导出适配器，每个一个模块，附黄金样例
│  │  ├─ plugins/                插件注册（入口点）与基础协议
│  │  ├─ resources/              内置提示词（*.j2）、评分量表、配方模板、JSON Schema
│  │  └─ worker/                 Redis Streams 消费者、作业执行、租约
│  └─ tests/                     unit/、integration/、e2e/、fixtures/（导出黄金样例）
├─ web/                          前端（见 web/CLAUDE.md）
└─ docker/                       Dockerfile、compose.yml（项目名 `ragflow-datafactory`）、env 示例
```

依赖方向（CI 中由 import-linter 强制）：

`app → (corpus, engine, tasks, quality, review, release, adapters) → (domain, store, gateway, core)`；`domain` 只依赖 `core`；`gateway` 只依赖 `core` 和自身 DTO；`adapters` 只通过 `release.ReleaseReader` 读取发布，不访问仓储。`worker` 可以导入任意服务包，但任何包都不导入 `worker`。

## 技术栈

- Python 3.13、`uv`、FastAPI + Uvicorn、Pydantic v2、SQLAlchemy 2.x（异步，`asyncmy`）+ Alembic、`redis`（Streams）、`minio`、`pyarrow`、`httpx`（Gateway 客户端）、`jinja2`（仅 SandboxedEnvironment）、`datasketch`（MinHash）、`numpy`、`structlog`。
- 引擎热路径不用 pandas，使用 pyarrow 表和普通 Python 行。不使用 RAGFlow 的 ORM（Peewee）。
- 只有在标准库或已有依赖无法满足时才新增依赖，并在 PR 描述中说明原因。

## 领域规则

### 数据模型（设计文档 §6）

- `ContentPart` 是唯一的多模态内容单元。所有承载内容的字段（段、查询、生成结果、消息）都是 `list[ContentPart]`。
- 媒体以 `asset_id = "sha256:<hex>"` 引用。MySQL 中不存 Base64 媒体；规范数据中不放框架占位符（`<image>`、视觉 token），由适配器插入。
- 事实层（L2）与任务无关：`Query`、`Judgment`、`Generation`、`Conversation`。任务特有的结构只存在于 Sample 视图（L3）。新增任务类型 = 新增 `TaskView`、门禁、模板与适配器，不得为某一任务在事实表上加列。
- `Judgment` 保留所有来源（`generator | miner | teacher | human`）；人工判断是覆盖（supersede），而不是改写原记录。
- 发布不可变。不得为发布内容增加更新/删除路径；弃用只是一个标记。
- `split` 由 `group_key` 一致性哈希得出。不暴露直接设置 split 的接口；修订后触发重新校验。

### 配方与引擎（设计文档 §7）

- 配方 JSON（Pydantic 校验）是唯一的持久化配置。`ui_layout` 单独存储，执行器从不读取。不得从执行结果或 UI 表单状态推导或改写配方配置。
- `required_columns` 由计算得出（Jinja AST、`multimodal_context`、参数引用），不接受客户端传入。
- 每种列类型实现同一协议：`config_model`、`granularity`（`cell | batch | global`）、`required_columns()`、`validate(ctx)`、`estimate(ctx)`、`run(...)`，通过 `plugins/` 注册。列之间不得互相调用。
- 单元格缓存键 = hash(列配置, 依赖列值, 模型指纹, gen_conf, 提示词资源哈希)。预览与正式运行共用执行器和缓存，不存在单独的预览代码路径。
- 确定性：采样器随机数来自 `hash(run_seed, row_key, column_name)`；行键来自种子单元，不来自批次序号。
- 批次提交携带 `attempt_generation`，写入时拒绝过期 attempt。
- Jinja：`SandboxedEnvironment` + `StrictUndefined`，自定义过滤器只来自 `engine/templating.py`。
- 不执行任意用户代码（不支持用户编写的 Python 校验器、不支持上传插件）。远程校验器的 URL 必须在白名单内。

### 模型调用

- `engine/model_client.py` 是调用模型的唯一路径（Gateway `models:invoke`）。列只依赖 `ModelClient` 协议。
- 每次调用前在数据库事务中预留"调用次数 + Token 上界"，返回后按实际用量结算。结果不确定（发送后超时、连接重置）记为 `billed_unknown`，**不自动重试**。
- 并发：每个模型使用 AIMD，令牌在 Redis 中共享；遵从 Gateway 的 429。不要在列中自行添加重试或 sleep。
- 每次调用写入 `Invocation`：脱敏请求、原始响应、解析结果、用量、延迟、尝试次数、状态。INFO 级日志只记录请求摘要，不记录完整提示词。
- 模态能力在配方校验阶段检查（含图片上下文的列必须选择视觉模型），不要等到运行时才发现。

### 难负例与质量（设计文档 §8、§10）

- 召回：稠密召回经 Gateway `search:dense`，查询使用知识库自身的 Embedding 模型编码；线上视角经 `search:production`。只有 `embd_id` 与维度一致时才允许跨库稠密检索，否则分库挖掘后按教师分合并。
- 候选成为负例前的强制排除：正例本身、其父/子段（`mom_id`）、与任一正例近重复（MinHash Jaccard ≥ 0.8）或存在包含关系的段、同一查询的其他正例。
- 默认采用正例感知筛选（`topk_percpos`，比例 0.95）。疑似假负例（教师分 ≥ 正例教师分 × 0.9 或绝对值 ≥ 0.8）进入审核，不得作为负例发布。
- 门禁以代码实现于 `quality/gates.py`，按任务类型区分。阈值可按项目配置，每次覆盖都记录原因。阻断级门禁不能通过 API 绕过。

### 适配器（设计文档 §11）

- 实现 `ExportAdapter`（`validate`、`export`），声明 `task_types`、`modalities`、`options_schema`。
- 不兼容的样本在 `validate` 中逐条列出并拒绝，不得静默丢弃。"仅导出文本子集"是显式选项。
- 媒体以相对路径 + 文件输出；只有目标格式要求时才内嵌 Base64。
- 编写适配器前，对照目标框架当前的官方文档确认格式，并在适配器模块的 docstring 中记录文档 URL 与版本。
- 每个适配器都有黄金样例测试：固定发布夹具 → 逐字节一致的期望输出。

## 环境隔离（强制）

- 91 为开发环境，92 为生产环境。开发期间不连接、不部署、不重启、不修改 92 上的任何内容。
- 92 上的 RAGFlow 存储由两个环境共享。DataFactory 自身资源必须按环境划分：

| 资源 | 开发（91） | 生产（92） |
|----|----|----|
| MySQL 数据库 | `datafactory_dev_<host>` | `datafactory` |
| MinIO 桶 | `datafactory-dev-<host>` | `datafactory` |
| Redis 键 / Stream 前缀 | `df:dev:<host>:` | `df:prod:` |
| Gateway 服务密钥 | 独立 | 独立 |

- `core/settings.py` 启动时强制检查：`DF_ENV=dev` 时数据库名、桶名、Redis 前缀必须包含 `dev`，否则拒绝启动。不要添加跳过该检查的开关。
- 开发运行会经 RAGFlow 调用真实模型并产生费用。使用开发项目预算，先预览，测试运行保持小规模。集成测试不得指向生产数据。
- DataFactory 的 Stream 名不得与 RAGFlow 解析队列（`te`、`te.dev.*`）重名。

## 常用命令

后端（在 `datafactory/backend` 下）：

```bash
uv sync --python 3.13
uv run alembic upgrade head
uv run uvicorn datafactory.app.main:create_app --factory --port 9390 --reload
uv run python -m datafactory.worker --queues default,preview
uv run pytest tests/unit                              # 默认层级；不依赖外部服务
uv run pytest tests/integration -m integration        # 需要按开发环境隔离的 MySQL/Redis/MinIO + Gateway 桩或开发 Gateway
uv run pytest tests/e2e -m e2e                         # 对开发环境 RAGFlow 跑完整流程；小预算
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run lint-imports
uv run python -m datafactory.app.openapi > ../web/openapi.json   # 任何 API 变更后执行
```

Gateway（在仓库根目录、RAGFlow 环境下）：

```bash
uv run pytest test/unit_test/api -k gateway
ruff check api/apps/restful_apis/gateway_api.py api/apps/services/gateway_service.py
```

部署命令写入 `files/operations.md`（首次部署时新增 DataFactory 章节），不要在此重复。

## 测试

| 层级 | 标记 | 依赖 | 默认运行 |
|----|----|----|----|
| unit | 无 | 无外部服务；Gateway 用 `tests/fixtures/gateway_stub.py`，MinIO 用内存实现，SQLite 仅用于与具体数据库无关的仓储逻辑 | 是 |
| integration | `integration` | 按开发环境隔离的 MySQL/Redis/MinIO | 否 |
| e2e | `e2e` | 开发环境 RAGFlow + Gateway + 真实模型（预算受限） | 否 |

修改以下领域时必须覆盖：

- Gateway 客户端：NDJSON 流完整性（EOF 计数等于行数）、超过 1025 个切片的文档、403/404/429 处理。
- 快照：幂等重建、按 SHA-256 去重资产、过期检测。
- 引擎：DAG 解析与循环报错、未变更列命中缓存、采样器确定性、暂停/续跑/取消及过期 attempt 拒绝、预算预留与 `billed_unknown`。
- 挖掘：每一条强制排除规则、正例感知阈值、假负例分流。
- 划分：正例段与近重复查询不跨 split；修订后重新校验。
- 适配器：黄金样例输出；不兼容模态的拒绝。

不保留针对已删除行为的测试。夹具小而合成，随代码提交；e2e 中使用的真实文档在测试 docstring 中以公开 URL 引用，不提交文件本身。

## 编码约定

- API 与 Worker 全程异步 I/O；CPU 密集工作（MinHash、Parquet 编码）放到线程/进程池，不阻塞事件循环。
- 仓储返回领域模型，而不是 ORM 行。路由调用服务，服务调用仓储和 Gateway 客户端；路由中不写业务逻辑。
- 错误：抛出带稳定 `code` 的 `core.errors.DFError` 子类，由应用映射到 HTTP 状态码。不得返回 200 加错误体。
- API：前缀 `/api/factory/v1`，游标分页，创建类接口支持 `Idempotency-Key`，长任务返回 `job_id` 并经 SSE 推送进度。OpenAPI 由代码生成，是前端类型的唯一来源；响应模型必须显式声明。
- ID：由 `core.ids` 生成的 `<prefix>_<ulid>`。API 中不使用数据库自增 ID。
- 时间：存储 UTC，在边界处格式化。
- 日志：`structlog` JSON，绑定 `request_id`、`run_id`、`batch`、`invocation_id`。INFO 级不记录密钥、完整提示词或用户内容。
- 迁移：每次 Schema 变更一个可回滚的 Alembic 修订；不修改已应用的修订。
- 提示词、量表、模板以文件形式放在 `resources/`，其内容哈希记录在配方版本中；不要在 Python 中内联长提示词。

## 文档维护

- 产品/架构变更：在同一次改动中更新 `design/PRODUCT_DESIGN.md`。
- 按仓库规则：`files/update.md` 记录整体原因与更新描述；`files/issue.md` 记录可复现的排查、修复、验证与回退步骤；`files/operations.md` 记录部署与运维操作。不修改 `docs/`。

## 审阅清单

- 没有导入 RAGFlow 模块或直接访问 RAGFlow 存储；Gateway 改动保持通用且只读。
- 没有凭据、数据库中没有 Base64 媒体、规范数据中没有框架占位符。
- 配方只有一种表示；依赖由计算得出；预览与运行共用执行器。
- 每次模型调用前预留预算；不确定的调用不自动重试。
- 强制负例排除与泄漏校验完整。
- 环境守卫完整；开发期间不触碰 92。
- 旧代码路径已删除，而不是与新路径并存。
