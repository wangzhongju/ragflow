# RAGFlow 问题排查与修复记录

[更新日志：整体原因与更新描述](update.md) · [稳定部署与操作手册](operations.md)

- **用途：**按日期保存故障现象、证据、修复、验证与回退；稳定操作见 [操作手册](operations.md)。
- **记录口径：**日期章节中的“本次/本轮”、主机状态、测试通过数量、模型响应和私有备份均指该日原记录。本次只对照本地代码，不重新证明历史现场结果。
- **环境边界：**本地与 91 为开发范围；92 为生产及共享存储。历史生产操作仅供审计，不是本次执行授权。即使请求发往 91，也必须先确认数据库、Redis、索引和对象存储已隔离，再进行写入测试。
- **本次核对：**2026-11-12，仅修改文档；未连接 91/92、未调用模型、未执行部署或业务测试。历史 ID、端口、模型和镜像标签使用前须重新核实。
- **与更新日志的对应：**[update.md](update.md) 只存整体摘要；其中缺少 11 月 3—4 日的六个专题摘要，本次不扩大修改范围补写。对于仅存摘要的旧条目，在相应日期标记证据缺口，不补造排查或验收结果。

## 目录

- [2026-11-04](#date-2026-11-04)
- [2026-11-03](#date-2026-11-03)
- [2026-11-02](#date-2026-11-02)
- [2026-10-30](#date-2026-10-30)
- [2026-10-29](#date-2026-10-29)
- [2026-10-27](#date-2026-10-27)
- [2026-10-26](#date-2026-10-26)
- [2026-10-24](#date-2026-10-24)
- [2026-10-23](#date-2026-10-23)

<a id="date-2026-11-04"></a>

## 2026-11-04

<a id="external-file-parse"></a>

### 外部 Agent 独立文件解析接口

- **2026-11-12 静态核对：**接口、服务、Skill 和测试文件均存在。实际路径为 `/api/v1/files/parse`；文件上限 20 MiB，整个 multipart 请求上限为 20 MiB + 64 KiB；支持 `Plain Text` 与 `DeepDOC`。下文 11 项通过为历史结果。
- 底层 PDF/DOCX/Markdown 解析可能调用租户视觉模型；无知识库入库不等于零模型调用或零计费。

#### 需求与定位

- 外部 Agent 需要上传文档并取得解析文本。先检查 Go 的文件解析与 MCP 入口，再核对 operations.md，确认现有部署运行 Python；最终在 Python 路径实现，未修改 Go。现有 FileService.parse 已完成格式分派、解析模式与文本拼接，直接复用该入口，避免另写解析器。
- REST API 模块由 `api/apps/__init__.py` 自动发现并注册到 `/api/v1`。

#### 修改位置与契约

- api/apps/restful_apis/file_parse_api.py：GET/POST /files/parse，只接受已有 AUTH_API 鉴权，上传一个 file，校验大小及模式，使用长任务线程池执行。
- api/apps/services/file_parse_service.py：允许的格式与模式、文件名规范化、20 MiB 限制、调用现有 FileService.parse 并返回文本。
- sdk/skills/ragflow-parse-file/SKILL.md：供外部 Agent 分发安装的调用流程。它不是 MCP 服务；MCP-only 客户端需要在自己的工具服务中封装 HTTP。
- test/unit_test/api/apps/restful_apis/test_file_parse_api.py：真实 Quart 请求测试，隔离数据库鉴权与原生解析依赖。

#### 本地检查及实际结果

- Windows Python 3.14 下 11 项测试通过，Ruff 检查通过。覆盖成功响应和租户传递、Windows 文件名、认证装饰器配置、空文件、不支持的扩展名、未知字段、重复模式、20 MiB 超限、解析异常脱敏、能力查询、错误媒体类型及多个文件。
- 真实鉴权查询与 PDF/OCR 未在本轮测试执行，不能把 stub 测试当作部署验收。Skill 用 UTF-8 模式运行校验器通过；默认 Windows GBK 模式不能读取中文 UTF-8 Skill，应使用 python -X utf8。

```bash
python -m pytest test/unit_test/api/apps/restful_apis/test_file_parse_api.py -q
python -m ruff check api/apps/restful_apis/file_parse_api.py api/apps/services/file_parse_service.py test/unit_test/api/apps/restful_apis/test_file_parse_api.py
python -m ruff format --check api/apps/restful_apis/file_parse_api.py api/apps/services/file_parse_service.py test/unit_test/api/apps/restful_apis/test_file_parse_api.py
```

#### 开发发布与再次排障步骤

1.  确认目标为 192.168.88.91，进入 /home/cdky/workspace/github/ragflow，核对当前版本与待发布差异。92 是生产，不同步、不执行重启。两端共享存储，避免创建测试知识库或修改模型配置。
2.  将两个新 Python 文件随审核后的版本同步到相同路径，保存当前版本用于回退；执行 `bash docker/docker.sh restart app`，观察应用启动日志是否有导入错误。此文档给出发布步骤，本轮未执行服务器同步或重启。
3.  参照 [接口文档](operations.md#file-parsing)，设置服务地址与已有用户 API Key，先 GET 查询能力，再上传内容为 hello agent 的 TXT。预期 HTTP 200、code=0、content 包含该文本。不要把密码当 API Key。
4.  404：检查两个新文件是否已发布、自动注册是否成功、是否重启以及代理是否转发到 Python 9380；401/403 或认证业务错误：检查 Bearer 格式、API Key 和所属用户有效状态。不要在日志中打印完整密钥。
5.  400：只传一个 file 和一个可选 layout_recognize，删除其他字段，检查扩展名及空文件；413：将文档拆分到 20 MiB 以下，并检查代理限制；415：改用 multipart 上传。
6.  422：在应用日志搜索 `External file parsing failed` 并读取该请求异常栈；先用 TXT 复测区分接口与解析器故障，再检查 PDF/Office 是否损坏、原生依赖是否齐全、OCR 模型是否存在。扫描 PDF 使用 DeepDOC，带文本层 PDF 先用 Plain Text。修复依赖需遵循已有镜像构建流程，不能向只读依赖卷临时安装。
7.  超时：检查文件规模和服务资源；底层解析可能仍在运行，不自动重复提交。接口无任务 ID、结果缓存或强制取消能力。验收补测 PDF 文本层、扫描 PDF、DOCX、XLSX 和中文表格，确认结果可用再交给外部 Agent。
8.  回退：将本次版本回退到已保存版本并仅重启 91 应用。该接口不新增数据库表、文件记录、对象存储写入或索引，无业务数据迁移需要撤销。

本轮只修改本地源码和文档，没有访问或修改 91/92 服务。工作区原有 CLAUDE.md 与 testdata 链接异常保持不变；检查差异时显式限定本次文件。

<a id="data-factory-pipeline-ui"></a>

### 修复数据制作管道画布加载错误

- **2026-11-12 静态核对：**Parser 表单仍使用数组；`transformParserParams` 按后端分别生成 Python 嵌套 `setups` 或 Go 顶层格式映射。下表示例限 Python。`update_agent` 仍维护版本与副本，但未提供本节修复所需的原子版本条件写入；
- 再次 GET 只能缩小并发窗口，写入前应暂停该管道编辑。

- 适用现象：智能体 → 数据管道打开后出现 `Something went wrong`，错误为 `TypeError: ((intermediate value) ?? []).map is not a function`，刷新仍失败。
- 本次对象实际名称为 `data_factory_multimodal_budget_20261104`，ID 为 `6f42931ed7f911f18ddbffc15ef7f57b`，排查与修复时间为北京时间 13:59–14:02。

#### 1. 修改清单与影响范围

| 位置 | 实际修改 |
|----|----|
| 共享数据库中上述管道的 DSL；经 91 的 `PUT /api/v1/agents/{id}` 更新 | 修正 graph.nodes 中 Parser 与 TokenChunker 的 data.form。没有直接执行 SQL。API 同时维护管道更新时间、版本及副本。 |
| Parser:HipSignsRhyme | setups 从对象恢复为数组，每项补回 fileFormat；按 order_index 排序。基于原模板保留表单专用字段，再合并当前执行设置，保留十二类格式、解析方式及模型选择。 |
| TokenChunker:PublicBusesYawn | delimiters / children_delimiters 转为 {value} 数组；image_context_size、table_context_size 映射到 image_table_context_window=128；运行重叠比例乘 100 恢复表单百分数（本次仍为 0）。chunk_token_size 保持 512。 |
| 91 私有现场目录中的 create-pipeline.py | 删除将运行 params 整体覆盖画布 form 的赋值；保留原模板表单，只设置 chunk_token_size=512、image_table_context_window=128，并断言 Parser setups 为数组、分隔符为 {value} 对象。 |
| 91 私有现场目录中的诊断、修复与浏览器验证脚本 / JSON 快照 | 新增定向修复和验证证据，文件清单见下文。均为本次特定实例的运维记录，不是通用生产修复命令。 |
| 工程文档 | issue.md 记录详细流程；update.md 记录阶段结果；当时的 `数据制作操作.md` 第 8 节记录表单/运行参数约束及复现指引；当前 `files/` 已无该文件。 |

本次未修改 RAGFlow 前后端业务源码、共享 UI、模型配置或队列配置，也未重启服务。修正的是已有管道数据和此前创建该管道的一次性脚本。91/92 共享业务数据库，因此该管道记录两端可见；并非只修改浏览器缓存。没有改动其他管道或重新解析知识库。

#### 2. 根因与代码定位

1.  浏览器控制台堆栈指向 `web/src/pages/agent/canvas/node/parser-node.tsx`：`(data.form?.setups ?? []).map(...)`。`?? []` 仅处理 null/undefined，对非空对象无效。
2.  Parser 表单要求 `setups: z.array(SetupSchema)`，见 `web/src/pages/agent/form/parser-form/index.tsx`；TokenChunker 表单约束见同级 `token-chunker-form/index.tsx:27`。
3.  `web/src/pages/agent/utils.ts` 的 `transformParserParams`和 `transformTokenChunkerParams`负责将表单转换为执行参数。这是两个不同的数据结构，不能整体互换。
4.  此前脚本使用 `node['data']['form'] = dsl['components'][node['id']]['obj']['params']`，破坏前端结构。执行器读取 components，因此文档能够解析成功，画布却打不开；仅验证后台解析无法发现此问题。
5.  更新接口 `api/apps/restful_apis/agent_api.py` 的 `update_agent` 校验运行组件，并维护版本/副本；本次接口未拒绝畸形画布表单。排查时必须同时检查 graph 和 components。

#### 3. 表单与执行参数对照

以下仅为格式示例，省略其他配置，不应将示例整体覆盖真实节点：

```text
# graph.nodes[].data.form：前端编辑数据
Parser:
  "setups": [
    {"fileFormat": "pdf", "parse_method": "DeepDOC", ...}
  ]
TokenChunker:
  "delimiters": [{"value": "\n"}, {"value": "!"}]
  "children_delimiters": []
  "image_table_context_window": 128
  "overlapped_percent": 10

# components[node_id].obj.params：后端执行数据
Parser:
  "setups": {
    "pdf": {"order_index": 0, "suffix": ["pdf"], "parse_method": "DeepDOC", ...}
  }
TokenChunker:
  "delimiters": ["\n", "!"]
  "children_delimiters": []
  "image_context_size": 128
  "table_context_size": 128
  "overlapped_percent": 0.1
```

若图片和表格上下文大小不同，当前统一窗口表单不能无损表达，不能静默取任意一个值。本次两者同为 128，已断言相等。页范围等表单专用字段应从已知正常模板或备份保留，不能依靠运行参数完整反推。

#### 4. 同类问题排查步骤

1.  **确定目标。**记录访问主机、页面 URL、管道 ID 和实际名称，不按近似名称批量修复。浏览器开发者工具查看第一条组件异常及调用栈；确认 API 返回成功后才检查 DSL。其他组件的 .map 异常不可直接套用 Parser 修复。
2.  **备份当前记录。**通过当前用户授权的 `GET /api/v1/agents/{id}` 保存完整响应及更新时间到私有目录，文件权限限制为当前维护者。检查响应 code；若 dsl 为字符串，先 JSON 解码。不要把凭据写入日志、文档或 Git。
3.  **核对结构。**定位 graph.nodes 对应 node.id，检查 data.form.setups 是否为数组；再检查 TokenChunker 的两个分隔符数组及统一上下文窗口。与 components 同一节点和正常模板对照，记录模型、解析方式、顺序、分块大小、上下文及重叠比例。
4.  **确定损坏来源。**检查创建/导入/克隆脚本是否直接复制 params 到 form。此次错误来自私有创建脚本，前端源码并未更改。不要以空数组兜底隐藏现有配置，也不要通过重建知识库绕开表单问题。

#### 5. 定向修复与验证步骤

1.  从新备份复制 DSL，仅修正确定损坏的节点 form；保留 node ID、布局、边、模型引用及其他设置。Parser 按 order_index 重建带 fileFormat 的数组；TokenChunker 按前述单位和结构转换。
2.  提交前再次 GET，比较最新 DSL/更新时间与备份，避免覆盖期间其他人的编辑。保存前断言 components 未变；通过 `PUT /api/v1/agents/{id}` 提交 dsl，并保留该记录原有 canvas_type 和 release 值。该接口会为缺省 release 赋 false，不能在修复时遗漏这些状态。检查返回 code，而非只检查 HTTP 200。
3.  保存后重新 GET，核对目标 form 和 components。打开实际 Web 页面，等待四个节点出现，依次打开 Parser、TokenChunker；不能以页面刚出现导航栏作为成功。
4.  检查 Parser 十二类格式、LLM/ASR 选择；检查 TokenChunker 为 512、128、0% 及原八个分隔符。点击 Save，确认 PUT 成功，然后刷新并再次打开节点。
5.  再次比较保存前后 components 应完全一致。本次验证结果一致、浏览器无页面错误，原八页 PDF 仍为 DONE / 31 Chunk；未点击 Run/Publish，没有新增模型调用。
6.  同步修正创建脚本，新增结构断言；后续新建管道必须验收“页面打开 → 节点编辑 → 保存 → 刷新 → 执行参数比对”，不能仅检查解析完成状态。

#### 6. 现场证据与回退

91 历史私有记录目录：`/home/cdky/.local/share/ragflow-data-factory/nov04/`。原记录称以下文件存在；本次未连接服务器，无法重新确认。

| 文件 | 用途 |
|----|----|
| pipeline-before-web-fix.json | 修复前完整 GET 响应，包含当时错误的画布数据及正常执行组件。 |
| pipeline-after-web-fix.json | API 定向修复后的完整 GET 响应。 |
| pipeline-web-verified.json | 浏览器保存并刷新后的 DSL 本体；与上两项的完整响应包装不同。 |
| pipeline-original.json | 克隆时的 model_pip_new 原始模板，保留正常表单结构。 |
| create-pipeline.py | 已纠正的一次性创建脚本；从模板保留表单、修改目标字段并断言格式。 |
| inspect-graph-error.py / repair-pipeline-forms.py | 诊断并修复本实例的脚本。修复脚本检查当前 DSL 等于原备份后才写入；现已修好，直接重跑会被断言拦住。 |
| pipeline-browser-repro.py / pipeline-browser-fixed.py / pipeline-browser-save.py | 修复前错误复现、修复后节点展示、浏览器保存刷新验收。 |
| verify-pipeline-persistence.py | 核对表单、执行参数和原八页文档状态。 |

- 回退前先备份当前最新记录，确认没有后续编辑。若本次修复造成意外变化，经同一 PUT 接口恢复备份内的 dsl、canvas_type、release，并重新核验运行组件；不要直接回滚共享数据库。
- 恢复 `pipeline-before-web-fix.json` 会同时恢复原页面错误，因此应优先从已验证的 `pipeline-after-web-fix.json` 或针对最新记录做定向纠正，不能把旧快照作为日常覆盖命令。

<a id="data-factory-v2"></a>

### 数据制作二期与开发解析队列隔离

- **2026-11-12 静态核对：**本地 `api/`、`web/src/`、`docker/` 未找到当时 `data_factory` 服务、内嵌页面或可选网关。下文二期能力和测试均是历史实施记录，不能用来证明当前可用。工作区另有独立 `dataforge/`，不能视为本节实现或使用其入口恢复旧服务。
- 当前仍能核对的队列功能见本节后半部分。

**历史入口：**`http://192.168.88.91:8088/data-factory`。仅标识 11 月 4 日记录中的页面，不作为当前可用链接。

#### 1. 架构与数据边界

- 移除独立静态工作台页面，在 RAGFlow 原导航的知识库与聊天之间增加入口，复用 React、组件库、布局、登录与请求层。后端保持独立业务模块，主应用仅增加可选网关；制作服务停用不要求删除知识库或修改主应用业务表。
- Embedding、Reranker、LLM 独立策略和 Payload，共享 Canonical v2、ContentPart、来源快照、审核修订、质量门禁、版本与 Adapter。支持 text/image/audio/video/structured；当前音视频生成使用解析文本和人工标注，未实现自动切段、专用音视频推理或训练。
- SQLite 保存业务元数据，MinIO 独立桶 ragflow-data-factory 保存文件，以租户与 SHA-256 去重；引用稳定资产 ID。原件、页图、图块、提取文本保留派生关系。导出相对路径、Manifest、分区 JSONL、来源与 SHA-256，不将媒体 Base64 写入业务数据库或把 ES 当原件库。
- 服务使用原开发镜像、独立持久卷、单 Worker、1 CPU/2 GiB，仅回环 9392；接入 ragflow-app_default 网络。旧发布 ZIP 按原字节保留，迁移前 SQLite backup 保存为 factory.pre-v2-nov04.sqlite3。

#### 2. 实现中发现的问题及修正

| 问题 | 定位与处理 | 验证 |
|----|----|----|
| 原生数值 Input 提交 undefined 字段 | 共享组件转换 number 事件时重建 target，DOM name/type 不是可枚举属性。功能内包装组件显式传递字段名与数值，不修改共享 UI。 | 浏览器提交 max_samples=1、max_calls=0、token_budget=0 成功；创建后 ready。 |
| 图块正文被误挖为负例 | 图 1 文本正例与包含同段正文的图片候选高度相关，Rerank 约 0.996。增加包含/近重复过滤、高相关隔离与发布门禁；相关候选人工改为多正例。 | 回归用例阻止错误正负配对；真实图文样本复核批准。 |
| 多文档重复与划分泄漏 | 对文本归一化去重，文档家族、重复内容与共用问题连通分组；租户内持久化分区，人工修改仍检查来源分区。 | 重复家族测试通过；拆分 PDF 演练来源未混入最终十页实例。 |
| HTTP 内网环境缺少 crypto.randomUUID | 采用工程已有 uuid 库；提交请求 ID 随有效配置固定，失败重试保持幂等。 | 实际 HTTP 页面创建、审核、冻结与下载通过。 |
| 模型费用与不确定重试 | 每次调用前事务预留次数与 Token 上界，检索编码、Rerank 独立计账，成功结果可复用；不确定调用不自动重试。 | 制作阶段真实外部调用共 5 次，其余模板/关键词演练为零调用。该数字不含知识库解析，也不是云账单 Token 数。 |
| 源资料虽解析完成但语义错误 | ASR 将数字语音转成解释而非逐字稿；TN 表格末行 ∞ 被识别成 8。检查原件后驳回两条对应样本，不以解析 DONE 作为训练质量合格。 | 最终 Embedding 实例 1 条批准、2 条驳回；冻结只含批准样本。待人工修正解析/转写后新建快照。 |

#### 3. 真实多模态语料与受控流程

1.  下载 NIST [TN 1297](https://nvlpubs.nist.gov/nistpubs/legacy/tn/nbstechnicalnote1297.pdf)，提取物理第 7、8、9、10、12、13、14、15 页组成原八页 PDF；
    - 补充 [SP 800-207](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-207.pdf) 第 14、18 页，PDF 合计十页，包含正文、公式、表格与架构图。渲染检查源页面。
2.  补充 [Vosk 短语音](https://raw.githubusercontent.com/alphacep/vosk-api/master/python/example/test.wav)、[MDN 五秒花朵视频](https://developer.mozilla.org/shared-assets/videos/flower.mp4)。NASA 音频下载返回 429 后更换公开样例，未反复重试；视频首末帧已人工核对。
3.  建立专用知识库“数据制作多模态验收_20261104”（a7a499b4d7f911f18ddbffc15ef7f57b）。
    - 克隆 model_pip_new 为 data_factory_multimodal_budget_20261104，保留 File → Parser → TokenChunker → Tokenizer，移除额外 Extractor/Compiler。原用户管道不改动。通过 documents/ingest 启动管道解析。
4.  用户配置的 qwen3.8-flash、qwen3.7-text-embedding-flash、qwen3.7-text-rerank 及 ASR 由 RAGFlow 模型适配调用。八页 PDF 31 块、两页 PDF 5 块、音频与视频各 1 块，共捕获 38 条证据；ContentPart 计数 text 38、image 13、audio 1、video 1、structured 1，一条证据可以包含多种 Part。
5.  实例内独立配置问题模型/提示词/预算、关键词或向量/混合检索、范围、阈值、召回量、权重、Rerank 与正负比例；检索编码沿用知识库匹配模型。无需跳转知识库修改制作实验参数。现阶段实例配置固定，变更配置创建新实例便于对照。
6.  审核后已冻结：Embedding 图文多正例 1 条，Reranker 1 条（导出两条分级行），LLM 图文 1 条、视频 1 条。Canonical、Pointwise 与 ShareGPT 包的 SHA-256、相对媒体路径及重复下载字节一致性通过；浏览器亦完成图片预览、批准、冻结和 ZIP 下载。

#### 4. 验证范围

- 8 项制作模块自动化测试通过：1025 块分页、快照续跑/取消、角色与撤权、修订、预算、三类任务、媒体、冻结和适配器拒绝；3 项队列命名测试通过。
- 前端专项 oxlint 无错误或警告，生产 Vite 构建通过。全仓 tsc 仍有既有错误（输出 301 行），本次功能路径无诊断；未宣称全仓类型检查通过。后端专项 Ruff 通过；common/constants.py 原有 BaseException 捕获触发 BLE001，与队列改动无关，单独排除该条后其余检查通过。
- 本轮临时停止制作服务的隔离验证命令被自动审批审查拒绝（blocked by policy，无进一步原因），未执行；不得将 11 月 3 日停用验证当成本轮复验。主应用当前健康，业务网关具备服务缺席返回 enabled=false 的分支。
- 未运行训练、训练后评测、规模压测或任意云模型的完整重现试验；Recall/MRR/NDCG 与吞吐由外部评测工程读取冻结数据计算。

#### 当时的定向修复做法（原制品取证用）

以下六项保留当时的处理思路。当前恢复前先取得原服务源码版本、镜像、SQLite/对象备份和配置，验证文件/数据一致后在隔离环境复现；不能仅凭本记录启动缺失模块。下列旧页面和文件名均不是现行入口。

1.  **数值配置：**在浏览器 Network 检查创建实例请求的 config；若出现 undefined 字段或预算未改变，核对 data-factory/create-instance.tsx 的 ConfigNumber 显式传递字段名，而不是读取被共享 Input 重建的 target.name/type。
    - 部署对应功能文件后，用 max_samples=1、max_calls=0、token_budget=0、模板问题和关键词检索创建实例；核对请求体及实例配置，勿修改共享 UI。
2.  **HTTP 请求 ID：**若控制台提示 crypto.randomUUID 不存在，核对同一创建页面使用工程 uuid 库及稳定的提交 request_id；刷新后重复提交同一请求，确认没有重复实例。变更配置时才生成新的请求 ID。
3.  **错误负例：**在样本审核中展开正例/候选原文和图片，比较重复、包含关系和 Rerank 分数；实际相关候选改为正例或移除负例，保留审核理由。困难负例不足时补充来源后新建实例，不用随机样本冒充。修订保存后运行质量检查，只有通过并批准的样本进入新版本。
4.  **重复/泄漏：**对照来源文档家族、内容哈希和 split；不同文档的相同段落不能跨训练/测试分区。不要手改数据库 partition 来绕过门禁，检查 embedding.py 的家族去重与一致分区逻辑，生成新实例后验证。
5.  **预算/不确定调用：**查看实例配置、作业状态和 invocation 记录；确认已有调用完成、失败或状态不确定。取消作业不会撤销已发出的云请求，不能不断重试。先使用零调用模板/关键词流程验证；需模型调用时重新限定次数、输出上限和预算。
6.  **ASR/OCR 错误：**试听原音频、阅读 PDF 原表格，将解释性“转写”和 ∞→8 等错误样本驳回，备注具体问题。纠正解析/标注后新建快照与修订，再审核冻结；本次未修复上游 ASR/OCR 模型，不能把驳回视为解析质量已恢复。

**历史测试入口：**当时在 `/factory` 执行 `data_factory.test_workflow` 与 `data_factory.test_contracts`；当前工程无这两个模块，不能直接复测。仍存在的队列测试可在隔离开发依赖环境运行：

```bash
python -m unittest test.unit_test.common.test_queue_namespace -q
```

<a id="queue-isolation"></a>

### 91/92 解析队列隔离与八页 PDF 重建

- **2026-11-12 静态核对：**`common/constants.py` 确实读取 `RAGFLOW_QUEUE_NAME`；`init_env.py` 为新 dev 配置生成 `te.dev.<IP下划线>`。
- `common/settings.py::get_svr_queue_name` 当前统一生成 `{前缀}.{优先级}.common`，不按任务类型创建独立后缀。仅队列分离不能证明存储隔离。

#### 1. 根因

两个应用连接同一 Redis 且解析前缀都为 te，开发 API 提交的八页文档被 92 Worker 消费；92 应用仅 6 GiB 配额，解析进程出现 Killed 和重试。此前“制作作业独立”不等于上游知识库解析队列独立，拆页也不能解决任务跨环境消费问题。

#### 2. 处理步骤

1.  核对任务、消费者与两机日志，取消原开发失败任务，保留历史队列记录；没有清空生产 Stream。
2.  在 common/constants.py 的队列命名入口读取 RAGFLOW_QUEUE_NAME，默认 dev 为 te.dev、prod 为 te；校验名称，拒绝 dev 显式使用 te。初始化脚本为新 dev 环境生成带应用 IP 的前缀。
3.  91 私有 docker/env/app.env 固定 RAGFLOW_QUEUE_NAME=te.dev91，重新创建 app 使 API 和所有 Worker 使用相同环境。92 保持 te，不部署本次数据制作代码或改变其配置。当前两级优先队列统一从同一前缀派生，后缀均为 common。
4.  原八页文档 cec3797ad7f911f18ddbffc15ef7f57b 重新提交管道解析（清理本次文档旧解析结果，不删除知识库）。新任务 f8fea29ed7fb11f1a52363278793cc6b 进入 te.dev91.0.common。

#### 3. 验收证据

- 八页 PDF 状态 DONE，31 Chunk，处理约 136 秒；日志显示解析、Embedding 与索引均完成。
- Stream 记录 1793761263937-0；消费者仅 task_executor_common_4b09529b3ec1_0（91）。92 日志未出现新任务 ID。
- te.dev91.0.common 和 te.0.common 均 pending=0；历史消费者记录未删除。两机应用当前健康，91 本次任务未发生 OOM。
- 生产仍使用原共享存储，队列隔离不会隔离数据库、知识库索引、账号或 MinIO。业务写入仍须按共享数据环境管理。

#### 复发时：队列检查、改配与重建

1.  在 91 查看应用日志和当前文档任务 ID，并对照已有授权范围内的消费者归属证据，核对消费者归属；只匹配本次任务，不能把旧消费者记录当作当前仍在消费。记录失败任务，先在知识库页面取消本次开发解析任务，等待 Worker 停止处理。
2.  进入 91 本工程 app，检查 API/Worker 共用的启动配置。以下命令打印前缀，不输出凭据：

```bash
# 仅在已核实存储隔离的 91 开发应用内检查；不进入 92
bash docker/docker.sh into app
python -c 'from common.constants import SVR_QUEUE_NAME; print(SVR_QUEUE_NAME)'
python -c 'from common.settings import get_svr_queue_names; print(get_svr_queue_names("common"))'
exit
```

对开发 Redis 的只读检查：使用上述实际队列名运行 `XINFO GROUPS`、`XINFO CONSUMERS`、`XPENDING`，组名以返回值为准。生产消费者归属需使用已获授权的运维证据；本任务不连接 92。

3.  备份 91 的私有 docker/env/app.env，再编辑其中唯一的 RAGFLOW_QUEUE_NAME 为 te.dev91。确认当前 common/constants.py 支持该变量；prod 保持 te，其他开发环境使用各自不同前缀。不要初始化已有 env 或覆盖连接凭据。
4.  任务停止后在 91 执行 `bash docker/docker.sh recreate app`，让 API/Worker 同时重新读取配置；仅 restart 不会重新创建容器环境。执行 `bash docker/docker.sh status app` 并重新检查实际前缀。不要清空生产 Stream 或迁移未知归属任务。
5.  知识库页面选择原八页文档，重新运行其数据管道；仅重建这一文档的解析结果。记录新任务 ID，检查它进入运行配置指定的开发队列（当时为 `te.dev91`），91 日志出现任务，消费者归属为 91；生产侧是否无消费不能仅靠开发日志下结论。检查文档 DONE、Chunk、图表、向量与索引，不以队列空替代业务验证。
6.  如果失败，先保留新任务日志，检查运行前缀、消费者和 OOM；取消此次重建任务再纠正配置。旧 env 备份仅供核对，不把 91 回退到共用 te 后继续提交。已清理的文档解析结果需用原文件重建。

<a id="date-2026-11-03"></a>

## 2026-11-03

<a id="data-factory"></a>

### 数据制作一期 · 91 开发环境

**2026-11-12 静态核对：**一期工作台不在当前 RAGFlow 业务目录中；二期记录也不代表当前部署状态。保留现场过程用于溯源，不提供恢复旧静态页面或旧制作服务的现行命令。

以下为 11 月 3 日记录；11 月 4 日的后续实施见二期章节。两者均需按章节开头的现状说明理解。

1.  **部署边界。**在 91 复用已安装的开发镜像，单独启动 Compose 项目 `ragflow-data-factory`。容器限制为 1 CPU、1 GiB，只向宿主 127.0.0.1 发布 9392。制作作业、租户内去重的配图、审核修订和导出包使用专用卷。主应用、反向代理与生产 Compose 均无需修改。现有入库流程仍使用 91/92 共享的 RAGFlow 存储和队列；本次创建的私有测试账号、知识库和原件保存在该共享存储。
2.  **接入差异。**旧 benchmark 的创建 token 辅助函数使用 /v1/system/tokens，实测 404；按当前 Python 蓝图改用 POST /api/v1/system/tokens。提供方实例的模型列表提供名称，GET /api/v1/models 提供可供建库使用的 model_id。测试只在新租户中配置本地 HuggingFace 实例。原项目接口与辅助函数均保持原状。
3.  **分页与任务恢复。**公开 Chunk API 对 page_size 的上限为 100。工作台每 100 条翻页，按唯一 ID 核对 total 并重新读取比对，再提交文档检查点。取消或重试通过作业代次阻止旧任务回写。Worker 重启后的 interrupted 状态要求操作者重新提供凭据；数据库中不留 API Key。
4.  **真实入库。**从 NIST SP 800-207 提取物理第 18 页，确认正文与内嵌的 954 × 340 架构图同页。91 上已有 BCE 模型权重，以独立、限额的 CPU 容器提供编码，仅接入开发应用 Docker 网络。新建私有知识库，上传单页 PDF 运行 DeepDOC，日志记录 OCR、布局识别、6 个块的生成、Embedding 和索引完成。未调用云模型。
5.  **真实制作。**捕获 5 个文本块与 1 个独立图块。图片端点按桶与对象键定位，工作台只读取经验证的“本知识库 ID-本 Chunk ID”图块，解码后按 SHA-256 固化。人工核对页可显示 1365 × 488 的切片配图。用两条示例决定演练改写、负例纠正与批准，使用本地模型进行一次向量挖掘。冻结包复导 SHA-256 相同；批次 \[2,3,768\] 在临时投影层完成反向传播。该单文档案例用于验收流程，不提供模型效果结论。
6.  **浏览器和隔离测试。**早期浏览器断言尝试执行动态脚本，被页面 CSP 拒绝。改用 Playwright 的元素断言，无需放宽脚本策略。在 91 镜像内使用临时数据库和本地 HTTP 夹具通过 4 项用例，覆盖 1025 块、重复提交、取消与重启续跑、角色隔离、撤权、冻结、下载等。另用真实账号验证页面打开、配图解码、已有版本下载及其摘要。
7.  **停用验证。**停止且只停止 workbench 后，91 的 /api/v1/language 仍返回 python，专用知识库文档查询仍返回 DONE 和 6 个切片。重新启动 workbench，既有训练集、快照与导出包可读。运行数据、专用账号的凭据位置、SSH 隧道、复测命令和卸载办法见当时的数据制作操作手册。

#### 当前复核与恢复前提

1.  先取得对应日期的原源码、镜像、配置与数据备份，并核对完整性；未经确认不重新启动旧工作台。
2.  当前通用 RAGFlow API 仍可按实际路由检查：账号 Token 使用 `/api/v1/system/tokens`，模型目录使用 `/api/v1/models`，Chunk 分页上限为 100。
3.  分页完整性、来源权限、取消代次和冻结摘要仍是验收要点；下文历史通过记录不能代替对当前独立数据制作工程的验收。
4.  如需恢复，先在隔离存储的开发环境验证备份可读、页面与接口契约一致，再核对来源计数和导出摘要；恢复失败保留原备份，停止本次隔离实例，不修改生产数据。

<a id="vscode-pytest"></a>

### 1. 解决容器内 pytest 导入提示

#### 重复出现时的操作步骤

1.  先核对容器、用户和解释器。容器终端执行 `/ragflow/.venv/bin/python -c 'import sys; print(sys.executable)'` 和 `/ragflow/.venv/bin/python -m pip show pytest`；只读 .venv 不直接安装。
2.  备份 /ragflow/.vscode/settings.json；检查 uv.lock 中的 pytest 锁定版本。本次为 9.0.2；若锁文件已变化，采用对应版本。在容器普通用户终端执行以下命令（仅工具目录缺包时）：

```bash
mkdir -p /home/cdky/.local/share/ragflow-vscode-test-tools
/ragflow/.venv/bin/python -m pip install --target /home/cdky/.local/share/ragflow-vscode-test-tools 'pytest==9.0.2'
```

3.  合并设置，给 python.analysis.extraPaths 追加该绝对目录，保留原数组项。确认 Python/Pylance 扩展运行在容器端且解释器为 /ragflow/.venv/bin/python。
4.  执行 Pylance: Restart Language Server；仍未刷新则 Developer: Reload Window。运行下述独立测试命令确认执行环境，而不只看红线。
5.  恢复时从备份还原本次新增设置；工具目录中其他内容不要批量删除。extraPaths 不改变运行时 sys.path，完整项目测试仍需完整开发依赖。

- 91 的 `/ragflow/.venv/bin/python` 缺少项目开发依赖 pytest，且 .venv 为只读镜像卷；Pylance 的 off 模式依然报告无法解析的导入。
- 已将与 uv.lock 一致的 pytest 9.0.2 及其直接依赖安装至宿主用户持久目录 `/home/cdky/.local/share/ragflow-vscode-test-tools`，并将该路径追加到 91 工作区 `python.analysis.extraPaths`。未改动应用依赖卷或业务代码。
- 当前容器 VS Code 问题面板显示无问题。该个人目录和 .vscode 均不通过 Git 同步，其他主机需单独配置。

- `extraPaths` 只负责 Pylance 静态解析，不会让普通 Python 进程自动找到 pytest。需要用该工具目录运行测试时，在容器终端为该命令显式指定 PYTHONPATH；
- 例如以下命令仅验证独立的连接生命周期测试，跳过项目 conftest、项目 pytest 配置及自动加载的插件，并非完整测试套件：

```bash
cd /ragflow
PYTHONPATH=/home/cdky/.local/share/ragflow-vscode-test-tools:/ragflow \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
/ragflow/.venv/bin/python -m pytest -c /dev/null --noconftest -o addopts= \
  -o cache_dir=/tmp/ragflow-pytest-cache -q test/unit_test/api/db/test_connection_lifecycle.py
```

- 本次 5 项通过。工具目录仅含 pytest 及其直接依赖，不包含项目所有测试插件或所有开发依赖；完整测试应准备项目指定的开发环境。若问题未刷新，检查 Python 解释器、extraPaths 路径和实际目录内容，再重启 Pylance。
- 原工作区设置备份位于 `/home/cdky/workspace/ragflow-deploy-backups/20261102-vscode-connection/settings-before-pytest-path.json`。

<a id="date-2026-11-02"></a>

## 2026-11-02

<a id="dev-prod-results"></a>

### 1. 官方资源缓存与开发/生产镜像拆分

- **2026-11-12 静态核对：**当前构建入口仍为 `docker/docker.sh`，资源清单在 `docker/manifests/official-artifacts.json`，运行检查在 `docker/scripts/verify_runtime.py`。
- 镜像 ID、资源校验及服务健康均沿用 11 月 2 日记录，未重新验证；现行操作见 [源码构建](operations.md#source-build)。

#### 问题与定位

构建资源与运行依赖混杂、前端更新依赖重编译镜像。按官方资源清单校验缓存并拆分 dev/prod；缺失与损坏文件有明确恢复路径。

#### 再次出现下载或构建问题时

1.  先执行 fetch --check，根据失败文件检查 third_partys 对应大小/哈希；保留报错，不能只看文件存在。
2.  按[资源下载和 SSH 隧道步骤](operations.md#source-build)恢复网络及缺失资源；已有 build.env 仅编辑，不重新复制覆盖。结束后关闭隧道并恢复开关。
3.  选择 dev/prod 构建到新标签，检查构建日志；不直接覆盖在用标签。资源齐全不代表 apt/npm/Python 包可断网重建。
4.  执行运行资源检查和应用健康验证；dev 验证 8088 的 Vite 更新，prod 验证静态资源。切换前备份私有 app.env、原镜像及源码。失败时按下面的备份对应回退，保留数据卷。

#### 当次验证记录

- 2026-11-02 完成：91 部署 ragflow-local:dev-20261030（447b2d49c479），92 部署 ragflow-local:prod-20261030（fdd489c88475）；标签沿用本次任务开始日期。两端应用健康，Web/healthz/ping 返回 200。
- 生产镜像在 91 构建后传到 92，完整镜像 ID 相同。

- 34 项官方资源在本地、91、92 校验通过；有效文件不重下，缺失官方文件通过临时 SSH 隧道下载验证。隧道已关闭，91 build.env 恢复关闭状态。
- 23 项缓存/部署入口测试通过，Shell/Python/YAML 语法和文件索引检查通过；Vite 配置 lint 无错误，仅有原有 console 警告。
- 两套镜像均使用纯源码副本、全新依赖卷、network=none 通过 9 项运行资源检查：普通用户、sudo/apt 索引、Python 3.13.11、模型、NLTK、Tika、tokenizer 和对应前端可用；测试副本、容器和卷已清理。
- 91 经 8088 WebSocket 实测源码更新，收到 Vite js-update 且容器 ID/启动时间不变；探针文件已删除。92 生产 HTML、JS 静态产物可访问。
- 91 原五个容器及 92 六个存储容器的 ID、启动时间、挂载和重启次数不变。两端仍通过 bind mount 读取宿主工程。
- Go 定向测试在准备阶段因缺少 office_oxide 原生库停止，未执行到测试；完整 CI、独立沙箱构建及业务压力测试未运行。

```bash
bash docker/docker.sh fetch --check
bash docker/docker.sh status app
bash docker/docker.sh into app
python /opt/ragflow-ops/verify_runtime.py
exit
curl -f http://192.168.88.91:8088/@vite/client
curl -f http://192.168.88.91:9380/api/v1/system/healthz
```

此前用户环境验证记录：两端 into 为 cdky/1000:1000，免密 sudo、标准 Bash 配置、指定 PS1 和 cmake 安装均通过。本次没有复验；HTML 编辑器已随格式转换移除。

#### 备份及回退

- 本次备份位于两台主机 `/home/cdky/workspace/ragflow-deploy-backups/20261030-dev-prod/`。source-head.tar.gz 保存修改前已提交源码；source.tar.gz 保存最初涉及路径和私有配置；
- app.env/storage.env、HEAD 与 containers.before.json 保存原部署信息。app-before-switch-20261102.env/json 保存实际切换前应用配置与容器信息；91 同目录保存两次成功构建日志，两机保存各自的禁网检查结果。备份权限受限。

回退前停止本工程应用，将归档解压到独立目录核对，再恢复旧源码、匹配的私有 app.env 与旧镜像。本次新增的受管源码文件按实际差异逐项清理，保留私有 env/home。原依赖卷和镜像保留，存储与业务数据无需回退，91 其他工程不参与。

<a id="chat-latency"></a>

### 2. 聊天图片描述请求长时间等待

- 91 的 t1 聊天，会话 42c817d6d11011f19f5f2327f921c6ea，14:56:52 提问“对图片迪丽热巴进行简单的描述。”。14:56:53.186 Embedding 完成；两次 ES 检索耗时 0.038/0.005 秒，14:56:53.271 进入模型流式调用。
- 15:03:45.100 模型调用完成并记录 82 tokens，HTTP 请求总耗时 412.4 秒、状态 200；数据库 update_date 同步更新，用户确认收到回答。

- 聊天配置使用 VLLM 实例 qwen3-text-generation，地址 http://192.168.88.169:9501/v1。模型接口实际报告底层为 Qwen2.5-7B-Instruct。当前 /models、/health 正常；最小流式请求输出 OK. 并于 0.11 秒结束，运行和等待队列均为 0。
- 累计完成请求延迟约 66757 秒，其中排队约 56873 秒，提示服务存在历史排队压力；这些是累计指标，不能将本次 412 秒直接归因为排队。进一步定位需 169 在 14:56—15:04 的请求/调度和 GPU 日志。

本次延迟集中在模型调用阶段，无证据指向 Vite 或前端编译。Nginx API 路由关闭响应缓冲，最终返回 200。日志中的 QUOTA_EXCEEDED 是 10 月 26 日会话历史，不是本次新报错。程序默认模型超时为 600 秒，因此可能长时间等待；本次在超时前成功完成。

本次用户消息 files=\[\]，给文本模型的上下文来自知识库检索文字，未传入原图片；生成文字不能作为实际视觉识别结果。排查未修改配置、清理会话、重启服务或操作存储，仅做只读核查及短模型探针。

#### 同类现象的定位与处理

1.  记录会话 ID、提问/完成时间、所选模型和附件；以本次请求 ID/时间窗口检索 API/Worker 日志，区分检索、模型首响应、输出与持久化耗时。
2.  从应用宿主执行 `bash docker/docker.sh logs app --since 30m`，对应 Nginx 请求耗时和最终状态。日期必须换成实际事件时间，不能引用旧会话里的额度错误解释新请求。
3.  只读检查模型服务 /health、/models 和队列/GPU 监控；需要历史排队结论时取得模型主机同时间窗口的请求/调度日志。累计指标只能说明历史压力。
4.  本次请求已成功返回，未实施重启或配置修改。复发时先判断仍在执行还是已失败；若证据确认模型排队，再由模型服务维护者处理容量或调度。缺少日志时保留“原因未确定”，不能直接调高超时或重启。
5.  必要的最小推理探针仍会调用模型，先限定输出与次数；默认先做无推理检查。核对 files 与实际模型输入，检索文本回答不能冒充原图视觉识别。

<a id="db-connection-warning"></a>

### 3. 数据库连接警告反复出现的原因

**2026-11-12 静态核对：**本节描述修复前的 `close_stale(age=30)` 行为；当前 `close_connection()` 已只归还本线程连接，不能把旧代码当作当前实现。故障复发仍须先排除真实网络、超时与连接池问题。

- 2026-11-02 已通过当前代码和隔离连接复现。api/apps/\_\_init\_\_.py 的请求 teardown 调用 close_connection；api/db/db_models.py 对 MySQL 执行 DB.close_stale(age=30)。
- Peewee 的 close_stale 遍历整个池的已借出连接，按 checked_out 时间强制关闭底层连接；它不会同步重置其他线程持有的 Peewee 状态。因此同一连接可能出现 is_closed=False，而 PyMySQL open=False、\_sock=None。
- 下次 SQL 在客户端抛出 InterfaceError(0, '')，此时 SQL 尚未发给 MySQL。

- RetryingPooledMySQLDatabase.execute_sql 捕获异常，输出 attempt 1/5，重连并 sleep(1) 后成功。137 是 API 进程 PID，(0, '') 是异常参数，并非 MySQL 服务端错误编号。
- 多数请求首次重试就恢复，下一条使用被关闭连接的请求又从 attempt 1/5 开始。

- Docker 每 30 秒请求 healthz，其 SELECT 1 也复用线程连接；请求结束又执行 age=30 清理，解释了日志的周期性。现场带警告的健康检查约 1.02 秒，无警告时约 0.003—0.02 秒，均返回 200。
- 配置中的 stale_timeout=300 与代码强制 close_stale(age=30) 是两套不同机制，修改前者不能消除后者的行为。

- 排查时 MySQL wait_timeout/interactive_timeout 均为 28800 秒，连接数 8/300，Connection_errors_max_connections=0，持续运行约 7 天。
- 独立诊断进程中只使用自己的连接和 SELECT 1，等待 31 秒后调用当前清理函数，稳定复现相同警告及 1.004 秒耗时；在持有连接的工作线程调用正常 DB.close 归还后，再查询 0.001 秒且无警告。诊断连接已关闭，未操作在用连接池。

#### 复发时先确认根因

1.  观察是否随 30 秒健康探针重复、单次延迟约 1 秒；记录 attempt 1/5、异常及时间。
2.  只读核对 MySQL wait_timeout、连接数、网络与健康检查状态，排除真实断连/连接上限；不要仅凭 InterfaceError 判断数据库服务故障。
3.  检查部署的 api/db/db_models.py 是否仍调用 close_stale(age=30)，并核对健康检查是否在所属线程归还连接。
4.  需要复现时使用独立诊断进程和 SELECT 1，不能在在线服务的共享连接池调用全池关闭。已修复代码应运行回归测试验证；实施修复见下一条。

本条对应当时的只读原因核查，实际修复单独记录于[“4. 修复数据库连接告警”](#db-connection-fix)。

<a id="db-connection-fix"></a>

### 4. 修复数据库连接告警

**2026-11-12 静态核对：**`close_connection()`、`check_db()` 与五项连接生命周期测试仍在，代码符合本节修复描述。本次只读核对，不重跑测试或复验两端健康。

`api/db/db_models.py` 的 close_connection() 对各数据库统一检查当前线程的连接状态，并调用 DB.close() 归还该线程的连接；不再扫描或强关其他线程借出的连接。Peewee 连接池仍按自身 stale_timeout 管理连接，原有真实断连重试保留。

- `api/utils/health_utils.py` 的 check_db() 将 SELECT 1 和游标关闭放入 DB.connection_context()，确保正常执行或 SQL 异常后都在所属线程归还连接。
- Quart 的同步处理函数与 teardown 可能在不同执行线程，因此健康检查自行管理连接作用域，不依赖请求结束回调。其他业务方法已有的连接/事务上下文保持原职责。

- 新增本地池回归测试覆盖：当前连接归还及重复清理、另一线程借出超过 30 秒的连接保持可用、工作线程连续健康探针、SQL 失败归还、连接建立失败报告。5 项均通过；同一测试在旧代码上 4 项失败。原 GaussDB 测试中保护 MySQL 全池强关的断言已替换为四类数据库统一归还当前连接。
- 变更文件基础/异步 Ruff 检查及新测试完整检查通过；原文件全规则检查的 171 条既有问题无新增，未扩大本次清理范围。

```bash
# 已安装项目测试依赖的环境，跳过与该测试无关的 NLTK conftest 初始化：
python -m pytest --noconftest -o addopts='' -q test/unit_test/api/db/test_connection_lifecycle.py
# 仅开发环境发布修复时执行；11 月 2 日的生产重启是历史记录：
bash docker/docker.sh restart app
```

- 91 使用隔离诊断进程复测：持有 MySQL 连接 31 秒后从其他线程调用清理，原 PyMySQL socket 仍可用，后续 SELECT 1 耗时 0.001 秒且无重试警告。两台 app 各运行两个诊断线程、共 40 次只读健康探针，全部成功，结束后池中借出连接为 0；
- 最大 SQL 探针耗时分别为 13.6/5.0 毫秒。诊断只使用独立连接，不修改业务数据或在用连接池。

- 91 dev 与 92 prod 的本工程 app 已重启并健康，Web/API/healthz 返回 200；重启后的多个健康检查周期未见 Database connection issue、DB execution failure 或 Failed to reconnect。
- HTTP 健康检查抽样约 3—36 毫秒，不再出现此前由重试带来的固定约 1 秒停顿。该结论对应本次观察窗口，真实数据库或网络断连仍会按原策略记录告警和重试。

- 源码原件、部署前容器快照和最新验收结果保存在两机 `/home/cdky/workspace/ragflow-deploy-backups/20261102-db-connection-fix/`。91 原有 5 个 RAGFlow 容器和 92 的 6 个存储容器的 ID、启动时间、挂载及重启次数均未变化；
- 只操作本工程 app。91 另有原本已累计重启 16650 次的 dify-db-1 继续自动重启，未对其执行操作，不纳入 RAGFlow 验收范围。若需回退，在所属主机恢复本目录中的 db_models.py.before、health_utils.py.before 到对应源码路径后仅 restart app；
- 无需回退业务数据。本次不继续追查模型排队。

#### 重复修复步骤

1.  在受影响主机备份 db_models.py、health_utils.py 和部署版本。对照上条确认同一根因，不对真实网络断连套用此修复。
2.  将 close_connection 改为只检查当前线程 DB.is_closed() 并归还 DB.close()，移除 MySQL 全池 close_stale 调用；真实断连重试保留。
3.  将 check_db 的 SELECT 1、游标关闭放入同一个 DB.connection_context()，保证建立、执行与归还在同一线程。
4.  运行上述五项回归测试，检查异常路径与其他线程连接保持可用，再同步对应源文件；缺 pytest 时依照[独立测试工具配置](#vscode-pytest)。
5.  仅重启受影响的本工程 app 加载源码，连续观察多个健康检查周期，核对 HTTP 成功、日志与连接归还；不要重启存储或其他 Compose 项目。
6.  如需回退，使用该次备份的两个源码文件恢复并 restart app；保留日志说明回退原因，业务数据库不回滚。

<a id="vscode-container"></a>

### 5. VS Code 连接容器的 Git 标记与红线

标准附加与解释器设置见[稳定操作手册](operations.md#vscode-attach)。本条保留当时的所有者与诊断记录。

<a id="vscode-git"></a>

#### Git 修改标记

- 本次 VS Code 源代码管理明确报告仓库所有者不匹配：容器中的 VS Code Server/扩展进程以 root 运行，而 /ragflow 属于 uid 1000 的 cdky，root 执行 Git 返回 dubious ownership；以 cdky 执行 Git 可以正常读取。
- 最佳长期配置是在上面的附加配置设置 `remoteUser` 为宿主机对应用户并重新附加。对于本次已建立的 root 会话，已仅将 /ragflow 加入容器 root 的 Git 安全目录列表，VS Code 随后显示修改；该 root 配置可能在容器重建后消失。
- 若必须以 root 附加，可在确认仓库确属可信后执行 `git config --global --add safe.directory /ragflow`，勿使用 `*`。

- 先确认编辑已保存，并分别检查 `id`、`git -C /ragflow status --short` 和 VS Code 的 Source Control 面板。若终端能看到修改而界面没有，检查 Git 内置扩展启用、工作区信任状态、Git 输出面板和文件装饰开关，再执行 `Git: Refresh` 或重新附加。
- 以 git status 与 git diff 为准，`M` 表示工作树或暂存区相对 Git 版本发生变化，未跟踪文件通常显示 `U`；被忽略文件不会显示。容器中 conf/service_conf.yaml、其模板和 bin 是单独挂载，可能显示为修改，与宿主工作树不同；
- 不要据此执行 git restore、暂存或提交，先核对挂载来源和实际 diff。

<a id="vscode-python-diagnostics"></a>

#### 红线诊断

- 本次 Problems 面板显示 Pylance、basic 类型检查：`db_models.py:123/130` 报 mixin 上的 `super().db_value/python_value` 属性未知，138 行也有 mixin 的 `is_null` 属性未知。
- 该 mixin 本身没有继承 Peewee Field，实际使用时与 CharField/TextField 多重继承，运行期可沿方法解析顺序找到方法；静态分析器单独分析 mixin 时无法确定后续基类。这些具体提示不能据此认定包未安装或程序必然运行失败。

- `db_utils.py:149` 中 `query: dict = None` 的类型声明不包含默认值 None，静态类型检查可以合理报告不匹配；其他提示要逐条区分动态 ORM 推断限制、注解不一致和真实缺陷，不能将全部红线一概视为误报。合理的代码修复是根据调用语义完善注解、为动态接口提供准确类型信息并运行定向测试；
- 不要为了清空界面全局关闭诊断。本次只整理配置并诊断这些示例，未批量修改业务类型或声称所有红线均已解决。

#### 操作顺序

1.  在容器执行 id、pwd、git -C /ragflow status --short；确认打开的是本工程容器。
2.  若 root 与仓库 uid 1000 不一致，优先把名称级附加配置 remoteUser 改为 cdky，断开并重新附加。无需重启业务容器。
3.  仅在必须维持可信 root 会话时添加 /ragflow 为 safe.directory；不加通配符。不改文件所有权或恢复挂载文件掩盖提示。
4.  核对 Git 输出和 Problems 的诊断来源；按上文区分 ORM 动态推断与真实注解问题。若主动选择关闭类型检查，见下一条，该选择并非修复代码。

<a id="vscode-typecheck-off"></a>

### 6. 按要求仅通过配置减少 Pylance 类型提示

- 按用户要求，91 容器工作区 `/ragflow/.vscode/settings.json` 的 `python.analysis.typeCheckingMode` 从 `basic` 调整为 `off`，其余设置保持不变。此选项关闭静态类型检查规则，包括本节所述 mixin 属性推断与 None 类型不匹配；
- Pylance 仍可提供补全、跳转及未解析导入等基础诊断。它只调整编辑器诊断，不修复代码缺陷，也不能保证所有红线消失。本次设置生效后，VS Code 问题面板显示未检测到问题。

- 设置为工作区级，覆盖前述容器样例中相同的默认设置。由于 .vscode 已被 Git 忽略，此次只修改 91 的个人工作区，不会自动应用到本地或 92。修改后若状态栏仍显示 Type Checking: basic，可在命令面板执行 `Pylance: Restart Language Server`；
- 仍未生效时保存打开的文件并执行 `Developer: Reload Window`，再核对状态栏。需要恢复静态检查时，将该值改回 `basic`。
- 修改前的设置备份位于 91 的 `/home/cdky/workspace/ragflow-deploy-backups/20261102-vscode-connection/settings-before-pylance-off.json`。

#### 操作顺序

1.  备份当前工作区 settings.json，并确认配置作用于容器窗口。
2.  只将 python.analysis.typeCheckingMode 调为 off，保留解释器、导入解析及其他设置；不要覆盖整个 JSON。
3.  重启 Pylance 语言服务，必要时重载窗口；查看状态栏和 Problems。未解析导入仍可能存在，按对应导入问题排查。
4.  恢复静态检查时改回 basic 或还原本次备份。该个人设置不经 Git 同步，不改变其他主机的配置。

<a id="date-2026-10-30"></a>

## 2026-10-30

<a id="source-build-dependency"></a>

### 1. 源码镜像构建依赖缺失（摘要档案）

- **摘要所载：**依赖镜像资源变化造成 ChromeDriver 等文件缺失；当时固定已核验摘要和资源方式，通过临时构建检查，未切换在用应用。现行构建见 [源码构建](operations.md#source-build)。
- **证据缺口：**仅存 `update.md` 更新摘要；原记录没有完整排查、原始日志和详细验收证据，本次未补造历史结果。
- **再次处理：**使用 [资源缓存与构建流程](operations.md#source-build)，记录实际版本、配置备份、执行命令、验收和回退。

<a id="date-2026-10-29"></a>

## 2026-10-29

<a id="mounted-deployment"></a>

### 1. 统一 Docker 部署入口与整工程挂载（摘要档案）

- **摘要所载：**统一 `docker/docker.sh`、Compose 和整工程挂载，依赖卷按镜像隔离。摘要称两端部署/存储验证通过，未执行压测或完整灾备演练。
- **证据缺口：**仅存 `update.md` 更新摘要；原记录没有完整排查、原始日志和详细验收证据，本次未补造历史结果。
- **再次处理：**使用 [现行部署流程](operations.md#deploy)，记录实际版本、配置备份、执行命令、验收和回退。

<a id="dev-user"></a>

### 2. 应用开发用户、可编辑手册与完整文件索引

**2026-11-12 静态核对：**现行 Compose 已整工程挂载。HTML 的浏览器编辑/草稿/保存机制随 Markdown 转换移除；编辑和保存直接使用文本编辑器。env/home/state 的职责仍保留，恢复既有部署不得重新生成凭据。

#### 原记录：缺失私有配置

- 本次发现 92 应用仍运行，但宿主机 app.env、storage.env 与 state 目录已缺失。应用 env 从在用容器恢复，storage.env 从 20261029-layout/source.tar.gz 恢复；恢复前逐项匹配 MySQL、MinIO、ES、Kibana 及应用连接凭据，未生成新密码。
- 恢复后的 env 权限 600，目录权限 700，副本保存在 20261029-dev-user/recovered-\*.env。state 由 docker.sh 创建并由入口重新渲染。

因此不能将“被 Git 忽略”理解为“部署时不需要”。已运行系统更新代码时保留 env、home、日志和存储卷；新机器使用首次 init 生成配套配置，恢复既有系统则使用原始私有备份。不要用 git clean -fdx 清理部署目录。

#### 原记录：用户环境、工具与验证

- 仅应用容器建立宿主同名用户和主组，UID/GID 与当前调用用户一致；在 91/92 均为 cdky / 1000:1000。用普通用户运行 docker.sh；通过 sudo 调用时读取 SUDO_USER。into app 以该用户进入 /ragflow 的登录 Bash，不以 root 进入。需要管理权限时执行 sudo；
- 存储容器保留原镜像用户和工具。

- 镜像包含 sudo、vim、bash-completion、less、git、curl、wget、unzip、procps、iproute2 和 ping。env.sh 配置免密 sudo；首次从 /etc/skel 创建完整个人 .bashrc/.profile，保留标准历史、别名和补全。
- 初始 PS1 与 91 的 vision-pipeline/docker/env.sh 相同：绿色用户名、紫色主机名、青色路径。工程环境变量独立放在用户自己的 .ragflow_env，Vim 使用个人 .vimrc。文件一旦存在，后续 into 不重写，用户可以自由修改。
- docker/home 绑定到 /home，重建后保留配置。基础镜像占用 UID 1000 的 ubuntu 账户重命名为宿主用户；Python 解释器位于 /opt/python，NLTK 数据迁至 /usr/local/share/nltk_data。

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

- 运行镜像保留 apt 软件包索引，可直接 sudo apt-get install；apt 缓存归 root 管理，普通用户通过 sudo 安装。此前 Unable to locate package cmake 源于构建时删除索引，已改为只清理下载的 deb 缓存。系统安装包位于容器可写层，容器重建后需重新安装；
- 长期依赖应加入 Dockerfile 的安装步骤。个人环境配置位于绑定的 docker/home，重建后保留。

```text
PS1='\[\033[01;32m\]\u@\[\033[01;35m\]\h\[\033[00m\]:\[\033[01;36m\]\w\[\033[00m\]$ '
```

<a id="offline-check"></a>

#### 离线运行资源检查

```bash
bash docker/docker.sh into app
python /opt/ragflow-ops/verify_runtime.py
exit
```

- 检查挂载源码、Python 及连接库、Tika 校验、tokenizer 离线编码、7 个 ONNX 模型、生产前端 index 或开发 Vite 依赖、当前 UID 文件写入、NLTK 和 sudo/apt/开发工具。
- 现场还在两台主机分别使用纯源码临时副本、全新独立依赖卷和 network=none 运行入口 --help 完成资源准备后检查；未复制宿主机忽略产物、未连接数据库或启动测试 Worker。测试容器、临时卷与副本随后清理。该检查证明所用运行镜像可补齐依赖，不替代完整源码镜像构建或业务负载测试。

<a id="user-rollback"></a>

#### 用户环境改造备份

- 两台主机的 `/home/cdky/workspace/ragflow-deploy-backups/20261029-dev-user/` 保存原源码差异文件、原提交号、容器/卷元数据、个人环境文件备份、最终镜像记录和离线检查结果。回退应结合记录的 HEAD、差异归档和私有 env，恢复匹配的入口与镜像；不要回退业务数据。
- 此前仅含受管 include 的个人环境文件已转换为标准 Ubuntu 配置，个人追加内容保留。

#### 同类问题的处理顺序

1.  应用仍运行但 env/state 缺失时，不执行 init 或重建容器。先把在用容器的配置及原私有备份保存到受限目录，不能在共享终端输出完整环境变量。
2.  从原 app 容器恢复应用配置，从可信备份恢复 storage.env；逐项核对 MySQL、Redis、MinIO、ES、Kibana 的连接地址、账号与凭据。无法核对时保留现状，不生成新密码。
3.  恢复文件到 docker/env，目录权限 700、env 权限 600；在宿主工程根执行 `bash docker/docker.sh config app`（存储主机也检查 config storage），只验证配置不打印密钥。state 为派生文件，确认原私有配置齐全后再由正常入口生成。
4.  进入应用检查 id、解释器、sudo 与个人配置；若 apt 报 Unable to locate package，先 sudo apt-get update 再安装，长期依赖写入镜像构建。重建后只保留在绑定 home 中的个人配置。
5.  按上文运行 verify_runtime.py，确认源码/依赖/工具可用；再检查应用健康和只读业务数据。回退使用本次备份匹配的源码、入口和私有配置，不回滚业务存储。

本条保存原操作手册中的用户环境、cmake、私有配置恢复及验证记录；没有原始证据的其他更新以对应条目的缺口说明为准。

<a id="date-2026-10-27"></a>

## 2026-10-27

<a id="tongyi-sync-results"></a>

### 1. 通义模型完整同步流程

**2026-11-12 静态核对：**同步脚本仍提供四阶段命令；但空闲检查硬编码生产前缀 `te`，不能覆盖开发队列。执行前按 [现行流程](operations.md#tongyi-sync) 核对所有实际前缀及任务。359/174 等数量、哈希和模型属性均为 10 月 27 日快照。

- 时间：2026-10-27；新容器启动于 09:38:55（UTC+8），健康检查通过。工作目录为 91 的 `docker/backups/tongyi-sync-20261027/`。
- 官网快照 **359 项**；按现有适配器映射 **159 项**，另保留 **15 项待复核旧条目**，最终目录/实例 **71 → 174 项**。新增 103 项，静态元数据更新 56 项，实际数据库更新 48 行，删除 0 项。200 个官网条目没有自动生成适配目录项，其中 12 项作为已有待复核条目保留；另外 3 个保留项未在官网快照中出现。
- 新增 `qwen3.8-flash` 等模型；页面 API 实测返回 Chat/Vision、上下文 1,000,000、工具调用/思考标记及 `verify=unknown`，两目录接口均为 HTTP 200、业务码 0、174 项。旧 `qwen3-vl-flash` 未被重新加入。
- 待复核旧条目包括部分实时语音、Omni、翻译模型，以及未在该快照出现的 `kimi/kimi-k2.5`、两个 DeepSeek-Llama 蒸馏模型。它们不属于已通过本轮适配/权限验收的新项；详细原因见报告。
- 4 个 Qwen3.5 条目给出 2027-01-19 10:00（UTC+8）的未来下线信息，本次未提前删除。后续按[维护策略](operations.md#tongyi-policy)维护已确认的公告/时间记录。
- 71 个既有模型的 ID、状态和 verify 保留；流程、3 份文档、3 个知识库、租户、模型组及其他实例模型记录的前后哈希一致。没有切换流程模型、重建知识库、发起计费推理或修改云端额度设置。
- 本地与 Linux 宿主机的定向测试、Ruff 检查通过；重新获取官网并生成计划，目录和数据库均无二次变更。新目录 SHA-256：`71b9b306969e325bc2655a93fc16cc1cbbb2230ae2c22dd8206699a62ac2633b`。配置、工具和文档同步本地/91/92。

复发时按[通义模型同步](operations.md#tongyi-sync)操作。

<a id="tongyi-omni"></a>

### 2. 官网 Omni 模型未接入原因复核

**2026-11-12 静态核对：**本节保留 10 月 27 日官网快照与映射差异结论，未重新探测云端模型。当前 `sync_model_catalog.py::_normalize` 仍按本地能力映射注册，模型调用能力须单独验证。

- 2026-10-27 复核：官方快照已包含 `qwen3.8-omni-flash`，其能力分类为 `Multimodal-Omni`，输入为 Text/Image/Audio/Video，输出为 Text。
- 同步脚本 `_normalize` 的 Chat/Vision 分支只识别 `TG/VU`，随后也不匹配 TR/ASR/TTS 分支，因此进入 `excluded`，理由为 `No matching Tongyi adapter for these capabilities/API`。
- 这是本地映射覆盖不足，并非官网缺项、下线或已证实的账号权限问题；该报告理由不能作为模型无法接入的结论。

- [官方模型说明](https://help.aliyun.com/zh/model-studio/qwen3-8-omni-flash)明确支持北京地域、Chat Completions/Responses、1M 上下文及文本输出；
- [Omni 调用指南](https://help.aliyun.com/zh/model-studio/qwen-omni)使用 `reasoning_effort` 调节思考。
- 现有 Chat/CV 路径有复用基础，但 Qwen3 通用规则仍使用 `enable_thinking`，音频路径使用原生 MultiModalConversation 和 ASR 参数，不能仅补名称就认定所有模态可用。

- 准确范围应为“完整拉取官方元数据，按当前映射注册部分模型”。后续需按模型协议和输入/输出模态细分支持能力，补齐非实时 Omni 的 Chat/Vision 映射及请求参数测试，再单独评估音频/视频入口；`qwen3.8-omni-flash-realtime` 属于 Realtime 协议，不能与非实时版合并处理。
- 本次仅核查并补充说明，未修改映射、注册项或线上调用行为。

<a id="t4-correction"></a>

### 3. t4 数据存储、局部修改与图谱依赖核查

**2026-11-12 静态核对：**当前 `POST /api/v1/agents/rerun` 会先清理文档索引，并移除其数据集导航引用，再启动下游。快照会剔除向量字段；从后段重跑前应验证能重新生成必要原文、向量和编译结果。

完整存储结构、关联字段、两类编辑入口、t4 现场 ID、单块 PATCH 与文档下游重跑步骤见 [数据存储、更新联动与 t4 局部修正](operations.md#data-storage)。

- 本次只读确认 t4 有 25 个普通块和 38 条文档图谱记录；题注 `图1. 迪丽热巴` 位于 chunk `cbae5b080fb2ca3b`，至少影响人物实体、关系、另一实体的英文描述和图谱 JSON。单块编辑会重算该块向量/全文分词，但不会自动更新 Graph 或中间运行快照。
- Parser/Chunker 结果编辑须显式重跑下游；该入口先删除当前文档全部索引，不能按单块增量操作理解。另发现 t4 摘要提示词未绑定正文，BM25 使用了无正文提示回复，完整重跑前必须修正运行 DSL 的摘要变量。已准备两份请求体但未提交，未改线上数据。

<a id="kibana-inspection"></a>

### 4. Kibana 检索数据查看步骤

- 入口为 `http://192.168.88.92:5601`，人工登录使用 `elastic/ELASTIC_PASSWORD`。已验证 ES 8.11.3、Kibana available、t4 单块读取、1024 维向量、Term vectors 和 Explain 查询。
- 完整 Console 请求、Discover 数据视图/KQL 和结果解读见 [Kibana 查看手册](operations.md#kibana)。BM25 是查询时评分，不是独立表；中文 whitespace 查询不能直接等同 RAGFlow 的完整检索流程。本次只读验证，没有修改索引或发起模型调用。

<a id="date-2026-10-26"></a>

## 2026-10-26

<a id="t1-t2-graph"></a>

### 1. t1/t2 图片关联、模型报错与空 Graph 排查

- **2026-11-12 静态核对：**Parser → 媒体存储 → TokenChunker → Extractor → Tokenizer → 编译/Graph 链已对照当前 Python 代码。文本分支丢弃 `img_id`、摘要优先全文分词、无输入 Graph 可报完成等边界仍存在；
- 下文具体调用错误和对象状态仅为历史证据。

#### 当前对象与核查范围

- 本次读取 91 新应用及其连接的 92 存储，时间为 Asia/Shanghai；本节描述当日 t1/t2，与 [10 月 24 日的 local 案例](#local-empty-graph)分开记录。
- 两台服务器与本地 HEAD 均为 `7339cfbede21a8d312a13c979dc3df83aede2ffc`，新应用仍使用 `ragflow-local:v0.27.2-progress-20261023`，新应用及四项存储健康检查均正常。

| 项目 | t1 | t2 |
|----|----|----|
| KB ID | `7a3d7636d10e11f19f5f2327f921c6ea` | `a7aa8c24d11011f19f5f2327f921c6ea` |
| 文档 ID | `ac6dc1c4d10e11f19f5f2327f921c6ea` | `c0980694d11011f19f5f2327f921c6ea` |
| 实际流程 | `no_model_pip` / `29addbccd0df11f184dc27e9a0ee1736` | `model_pip` / `47f1dfa4ce8f11f18a4cdf41f1d8e4ee` |
| 本次解析 | 15:28:58—15:29:00 | 15:42:14—15:42:32 |
| DOCX 媒体转文本 | true；VLM 配置为空 | false；指定 VLM |
| Parser 输出 | 88 个文本项，其中 4 项有图片引用 | 76 个文本、8 个表格、4 个图片项 |
| 最终 ES 原文 chunk | 3 个文本；0 个图片引用 | 13 个文本、8 个表格、4 个图片；4 个图片引用 |
| 文档状态 | run=3、progress=1 | run=3、progress=1 |

- 两库只有同一份 `成都开源计算-初步技术方案模板.docx`，直接读取 MinIO 原文件所得 SHA-256 均为 `f79cc0d6975c640200ae044213b9a6a5f177e64f9be3b3efccb22ed97f44d8ed`。
- 两文档自身的 pipeline_id 与所属 KB 一致，确实都执行了 dataflow。Embedding 均为通义 `text-embedding-v4`，本次两库均完成向量推理和索引写入。

- 核查覆盖当前配置、历史运行 DSL、任务和操作日志、Worker 错误、目标 KB 的全部 ES 记录、Parser 与最终 chunk 的图片对象。补充模型排查时查询一次模型列表，并发起三个最小诊断请求，均被服务端拒绝，详见下文“model_not_found 的确定原因与独立额度障碍”；未重建或修改知识库。
- 关键 13 个运行文件与本地统一换行后的 SHA-256 全部一致。

#### 无视觉模型为何仍能存图片，以及 t1 的关联实际在哪里丢失

图片提取、对象存储与模型生成描述是三个独立步骤。该事件中的文件为 DOCX：

1.  `rag/flow/parser/parser.py::_docx` 调用 `rag/app/naive.py::Docx`；
    - `deepdoc/parser/docx_parser.py::get_picture` 找到段落中的 `pic:pic`，读取 `a:blip/@r:embed`，通过 `document.part.related_parts` 获取图片二进制，包装为 `LazyImage`。
    - 这一步读取 Word 内嵌资源，不需要 VLM，也不是 PDF OCR。
2.  Parser 生成包含 `text/image/doc_type_kwd` 的结构项。t1 的 `flatten_media_to_text=true` 只把媒体类型改成 `text`，没有清除 `image`；视觉增强函数只处理 `image/table` 类型，所以本次没有对这些项生成图片描述。
3.  Parser 的 `_invoke` 遍历 JSON 项调用 `rag/utils/base64_image.py::image2id`：处理图片、编码 JPEG，通过 `STORAGE_IMPL.put` 写入 MinIO，并以 `img_id="imagetemps-<UUID>"` 替换内存图片。该事件中的实际桶为 `imagetemps`，对象键为 UUID。
4.  正常媒体分块会保留 `img_id`，Indexer 将它与 `doc_id/kb_id/content_with_weight` 一并写进 ES；接口对外通常命名为 `image_id`，图片读取接口拆分桶与对象键后取回字节。关联保存在 chunk 记录中，并非靠 MinIO 对象名猜测原文位置，也不是 MySQL 图片外键。
5.  **t1 当前没有完成第 4 步的关联保留**：TokenChunker 的文本分支跳过空字符串，且不携带输入 `img_id`；本次 4 个图片项的文本全部为空。因此 Parser 阶段的 4 个图片对象仍在 MinIO，最终 3 个文本 chunk 全部没有 `img_id`。运行 DSL 仍能追溯这些对象，但普通 chunk 检索无法通过它们展示原图。

- 实测 t1 四个对象键为 `e8d9057ed10e11f185eb1367b9404d93`、`e8d95588d10e11f185eb1367b9404d93`、`e8d9577cd10e11f185eb1367b9404d93`、`e8d9598ed10e11f185eb1367b9404d93`，大小分别为 15,203、79,761、43,359、112,614 字节，均可 stat。

- 若后续上传 PDF，才走 `RAGFlowPdfParser.parse_into_bboxes`：页面渲染、OCR、版面/表格识别后按坐标裁出图表和文本区域，再进入图片存储链。PDF chunk 预览还可能按合并后的坐标重新裁图；因此 MinIO 图片不一定是原文件内嵌图片，也可能是页面区域截图。
- 无 VLM 仍可提取/裁图，但不会自动获得语义描述。清空 VLM 配置本身也不是可靠禁用方式，媒体增强函数可能回退租户默认视觉模型；t1 本次跳过增强是媒体已标成文本。

#### t2 的三类模型调用均失败

运行 DSL 中 Parser 的 DOCX VLM、Transformer（后端组件为 Extractor）、Compiler 都指向模型 ID `7a87cfeed0df11f184dc27e9a0ee1736`：

- Provider：`Tongyi-Qianwen`，实例：`wzj_tongyi`。
- 模型：`qwen3-vl-flash`，类型值 9（Chat/Vision），注册验证状态 `unknown`。
- 实例端点：`https://dashscope.aliyuncs.com/compatible-mode/v1`。

- 15:42:16 的 4 次图片请求均返回 `404`、`model_not_found`、`Model not exist.`。15:42:17—20 的 25 次摘要调用也返回同一错误；15:42:28 的 Compiler 调用出现同一错误及 `ProviderErrorResult`。
- 单看 404 无法区分名称、地域或权限；进一步核实官方公告与同实例直连结果后，已确认本次使用了下线模型，见下一小节。当前错误不是此前 `Arrearage` 欠费错误。

- 图片请求异常在 `rag/app/picture.py::vision_llm_chunk` 被捕获，回调报错后返回空描述，后续仍继续。`enhance_media_sections_with_vision` 将空描述列表字符串化，现场 4 个图片项的文本成为 `['']`；这不是模型生成的有效描述。
- TokenChunker 又按设置拼接前后文本，所以图片 chunk 中可能看到上下文/图题，不能据此判断 VLM 已理解图片。

- t2 的 4 个图片 chunk 与 MinIO 关联仍完整。例如 chunk `0a29d435abdd5936` 的 `img_id` 为 `imagetemps-c44e0040d11011f185eb1367b9404d93`，对应对象为 15,203 字节。
- 问题在描述生成，不在图片未提取或 MinIO 未写入。

#### model_not_found 的确定原因与独立额度障碍

- **确定原因是模型下线，而 RAGFlow 目录仍允许选择。
- ** 阿里云 [延期下线公告](https://www.alibabacloud.com/en/notice/model_studio_notice_on_the_postponed_retirement_of_selected_legacy_models_7d0?_p_lc=1) 明确将 `qwen3-vl-flash` 主线及其两份快照列为 2026-10-10 00:00（UTC+8）停止服务的模型。
- 国内 [主线模型下线公告](https://www.aliyun.com/notice/118344) 的生效日一致。

10 月 26 日 16:11—16:12 从 91 应用容器复测，密钥直接从当前实例配置读取，不输出或写入证据文件；绕过 RAGFlow/LiteLLM，直接请求实例已有官方地址：

| 请求 | 结果 | 能证明什么 |
|----|----|----|
| `GET /compatible-mode/v1/models` | HTTP 200，180 个模型，缺少 `qwen3-vl-flash` | 当前密钥/端点可访问模型目录，但旧模型已不在列表 |
| 旧模型 `chat/completions`，仅 `Reply OK.`，输出上限 8 tokens | HTTP 404，`model_not_found`，request_id=`b761cf39-927f-9a05-b760-7680dd829bdd` | 无图片、无 pipeline、无 LiteLLM 仍复现，排除它们改写请求导致本次 404 |
| 在列的 `qwen3.5-flash`，合成人名/组织 JSON，输出上限 64 tokens | HTTP 403，`AllocationQuota.FreeTierOnly` | 另有免费额度耗尽/仅免费调用限制，尚未验证生成成功 |
| 同模型，64×64 纯红合成图片，输出上限 16 tokens | 同上 | 图片调用也受相同额度限制；未发送业务文档图片 |

- 第三、四项响应要求补充可用额度或处理控制台的仅免费调用限制。官方 [错误码说明](https://help.aliyun.com/en/model-studio/error-code) 还列出账号未完成验证等可能情况，具体控制台状态本轮未读取；因此不能断言只有一个开关问题，也不能据此声称账号所有模型均不可用。
- 两个 403 是切换模型时暴露的独立障碍，不是旧模型 404 的解释。本轮未关闭免费限制、充值、修改实例或替换流程模型，`qwen3.5-flash` 只是诊断对照，并未通过业务可用性验收。

- 页面仍显示旧模型的原因也已查明：`conf/llm_factories.json` 仍含 `qwen3-vl-flash`；
- `common/settings.py` 加载该静态目录，`provider_api_service.create_provider_instance` 可将目录模型批量注册，未取得验证结果的条目保存为 `verify=unknown`。当前条目正是此状态。因此本地“已注册/可选择”与服务商当前实际可调用模型不是同一件事；
- 后续应同步下线信息并校验所选模型，而不是仅修改模型展示名称。

#### 摘要另有正文未绑定及检索污染问题

- Transformer 的实际提示词仍为 `Text to Summarize:\n[Insert text here]`，`inputs={}`，输出目标为 `summary`。`Extractor._invoke` 虽然循环 25 个 chunk，但只有解析出输入变量后才替换逐块正文；
- `LLM._sys_prompt_and_msg` 只做已配置变量的格式化。因此本次发出的摘要请求没有实际 chunk 正文。即使模型恢复，也需把上游 chunks 绑定为正文变量并在提示词中引用，不能保留默认占位文字。

本次运行 DSL 的 25 个 `summary` 全部为：

```text
**ERROR**: MAX_RETRIES_EXCEEDED - litellm.NotFoundError: DashscopeException - Model not exist.
```

- `Extractor` 将错误字符串直接赋给摘要，没有转成节点失败。`Tokenizer` 又优先用非空摘要生成 `content_ltks/content_sm_ltks`，覆盖正文的全文检索分词；ES 的 25 条记录均出现错误文本的分词。
- `dataflow_service` 入库前删除 `summary` 字段，所以最终 ES 没有该字段，不代表摘要调用没有发生。

Indexer 的向量字段配置为 `fields="text"`，故本次向量仍根据正文生成；摘要没有自动拼入向量文本或 `content_with_weight`。当前配置实际影响的是全文检索分词，不能将其描述为已经完成“正文加摘要共同向量化”。需要明确希望增强哪一路检索，再设置字段和保留策略。

#### 为什么执行 Compiler 后 Graph 仍为空

本次不是缺少 Compiler，也不是文档没有绑定流程。模板组 `22f6f8c4ce8f11f18a4cdf41f1d8e4ee` 已解析出一个有效 `knowledge_graph` 模板 `compile_graph`；日志确认 25 个 chunk 进入编译：

```text
15:42:27 compile batch 1 (25 chunks) for template (1/1)
15:42:28 1/1 batches: 0 items
15:42:28 Document knowledge compilation done (1/1): inserted=0, updated=0, duplicates_dropped=0
```

- 同一时段 Worker 明确记录对应文档/模板的模型调用失败。调用池记录 `ProviderErrorResult` 后仍返回错误字符串；后续 `gen_json` 与 `_struct_unwrap_items` 没有把该字符串作为业务失败阻断，最终得到空实体/关系列表。
- Compiler 随后透传原文 chunks，Embedding 和写索引仍能完成；不能将零输出解释为“文档本来没有可抽取实体”。

- 15:53:45 创建的 Artifacts 任务 `5f04197ad11211f19f5f2327f921c6ea` 为 `structure_graph`，15:53:49—50 输出 `Scanning doc_graph rows...` → `No doc_graph rows found.`。
- 它只聚合 Compiler 已写入的文档结构，不会重新对普通文本做实体抽取；`dataset_structure_merger.py` 无输入分支直接报进度 1。

按 t2 KB 过滤的 ES 全量结果只有 25 条原文 chunk，entity、relation、graph 均为 0。因此这是上游编译失败造成的无输入，且完成状态掩盖了增强失败；不是已有图谱被前端隐藏。反复点击 Artifacts Graph 不会修复上游数据。

#### 处理顺序与验收

1.  替换已下线的 `qwen3-vl-flash`，并先解决所选模型的额度/权限问题，再分别验证 VLM 图片描述和 Chat 文本/JSON 输出。可分别选模型，也可使用已实测同时支持两种任务的模型；不要把本轮返回 403 的对照模型当作已验收替代品。
2.  修正 Transformer 的正文变量绑定，明确摘要是否用于全文检索、向量文本或独立字段。需要“保留图片但不做 VLM”的流程时，应单独控制增强，不靠媒体转文本间接关闭。
3.  代码改进应在错误所属层阻断：禁止将 `**ERROR**` 作为摘要/JSON 结果消费，防止错误分词入库；明确媒体增强失败、编译失败与合法零结果的不同状态；空图不得被误认为成功生成。
4.  配置修正后重新解析现有文档，核验 4 张图有有效描述、摘要与各块正文相关、检索分词没有错误文本、Compiler 写入非零实体/关系。重解析会清理旧切片/图片，应按已有备份和重建流程操作，不用 SQL 伪造完成状态。
5.  最后再生成 Artifacts Graph，验收非零节点/关系、来源文档和任务完成记录；仅看 100% 不足以通过。若文档内容变化，chunk 数量可变，不把本次 25 条作为固定验收值。

- 本轮只更新文档，不修改业务代码、不重启服务、不清空缓存、不重建知识库。
历史私有证据目录为已忽略的 `docker/evidence/`，本次未复验文件：

- `detail-20261026.json`：配置、运行 DSL、任务。
- `storage-20261026.json`：原文件哈希、ES 与图片对象。
- `runtime-20261026.json`：源码哈希和 Worker 错误。
- `model-availability-20261026.json`：模型目录及旧模型 404。
- `model-control-20261026.json`：对照模型两次 403。
- 凭据未写入文档或诊断脚本。

<a id="tongyi-retirements"></a>

### 2. 按官方公告清理通义模型目录并重新加载

本节是[t1/t2 排查](#t1-t2-graph)之后的实际配置变更。用户明确选择“只更新模型目录，我随后在页面选择流程模型”。本次没有替换流程模型、修改租户默认模型、重新解析文档或操作百炼计费开关。

#### 官方依据与更新结果

核查日期为 2026-10-26，两份公告的停止服务日期均已到达：

- [延期下线公告](https://www.alibabacloud.com/en/notice/model_studio_notice_on_the_postponed_retirement_of_selected_legacy_models_7d0?_p_lc=1)：明确列出的主线及快照模型于 2026-10-10 停服，包括 `qwen3-vl-flash`。
- [补充下线公告](https://www.alibabacloud.com/en/notice/model_studio_notice_of_retirement_for_selected_legacy_models_7d9?_p_lc=1)：补充数学、翻译、OCR、ASR、Omni、VL 等具体模型/快照的下线清单。按表格第一列的完整模型 Code 匹配，不能把推荐替代模型一并删除。

- 将公告明确下线的名称与原目录取交集，本次移除 61 项；`Tongyi-Qianwen` 静态目录和已注册实例 `wzj_tongyi` 均由 132 项减为 71 项。
- 完整名称、来源和新目录 SHA-256 保存在 [tongyi-catalog-20261026.json](../docker/manifests/tongyi-catalog-20261026.json)。没有批量增加或自动选择替代模型。

- 同一密钥的官方 `/models` 返回 180 项，用于交叉核查，不能充当全部服务类型的下线清单。例如 `text-embedding-v4` 未出现在该接口中，但本次文档解析实际成功使用它，所以保留。`qwen3-vl-plus` 主线也保留，仅删除公告点名的两份快照。
- 保留项不代表已逐个通过当前账号的权限、额度及生成质量验证。

#### 更新涉及三处状态

1.  `conf/llm_factories.json`：系统支持目录，供添加实例/模型时使用；API 启动时加载到 `FACTORY_LLM_INFOS`。
2.  MySQL `tenant_model`：已注册实例的模型清单；修改 JSON 或重启本身不会清掉历史注册项。
3.  容器内目录与进程内存：原部署把 JSON 打进镜像，宿主机改文件不会自动进入容器。
    - 本次在 `docker/compose/compose.app.yml` 增加 `../../conf/llm_factories.json:/ragflow/conf/llm_factories.json:ro`，再重建新应用容器，使 API/Worker 都重新加载；
    - 镜像仍为 `ragflow-local:v0.27.2-progress-20261023`。

#### 本次历史操作与备份

- 2026-10-26 先确认队列空闲，再备份目录/Compose 和被删注册项，清理 61 条记录后重建新应用容器；17:12:51（UTC+8）启动，健康检查正常，已注册与支持目录接口均为 71 项。两流程的选择保持原样。
- 此后 2026-10-27 已执行[完整同步](#tongyi-sync-results)。

- 历史文件备份位于两服务器各自的 `docker/backups/20261026-171150-model-catalog/`；91 的 `model-rows.json` 包含当时删除的 61 条记录，权限为 0600。容器日志目录另存 `tongyi-model-rows-20261026-171150.json`。
- 它们用于历史审计，不应直接覆盖后续用户修改。

只删下线项脚本已被完整同步工具替换，后续使用 [同步流程](operations.md#tongyi-sync) 的 `plan/apply/verify/rollback`。10 月 26 日的整工程挂载准备曾撤销；10 月 29 日已实施整工程挂载，当前不再是本节的文件级挂载。

- 复发时按[模型目录同步](operations.md#tongyi-sync)生成计划、审阅影响范围、应用和验收。
- 若调用报 `AllocationQuota.FreeTierOnly`，按[额度检查](operations.md#tongyi-quota)区分云端限制与本地配置。当次未读取或修改云端开关。

<a id="mount-prepare-reverted"></a>

### 3. 整工程挂载准备后撤销（摘要档案）

- **摘要所载：**10 月 26 日应用尚未切换时按要求暂缓，恢复本地及两端准备项；保留备份和此前模型目录更新。该撤销随后被 10 月 29 日的正式挂载实施取代。
- **证据缺口：**仅存 `update.md` 更新摘要；原记录没有完整排查、原始日志和详细验收证据，本次未补造历史结果。
- **再次处理：**先核对哪些准备项尚未上线，按变更清单撤回并比对原配置。已经切换的应用按[应用回退](operations.md#rollback)处理，不把旧撤销清单直接用于当前部署。

<a id="date-2026-10-24"></a>

## 2026-10-24

<a id="local-empty-graph"></a>

### 1. local 知识库报错及空 Graph 排查

- **2026-11-12 静态核对：**文档自身 `pipeline_id` 决定解析路径、Graph 聚合已有编译结果、视觉失败后仍可完成文本入库等行为仍可由代码核对。下列数量/模型/ID 仅属于 10 月 24 日快照。
- `inspect_task.py` 的队列检查仍硬编码 `te.0.common/te.1.common`，会遗漏开发前缀，须另外检查实际队列。

#### 排查范围与当前状态

- 本轮于 11:38 起从 91 应用读取 92 的 MySQL、Redis、Elasticsearch，并检查两台服务器源码及 91 当前补丁容器。查询不修改业务数据；
- 另从应用容器向本地 Embedding 发出一次合成短文本请求（8 tokens），未重试欠费通义服务。时间均为 Asia/Shanghai。

| 项目 | db_t1 | local |
|----|----|----|
| 知识库 ID | `f98bec50ce8f11f18a4cdf41f1d8e4ee` | `5ef3b38ecea911f18a4cdf41f1d8e4ee` |
| 当前文件 | ENNP用户手册_CN_v3.0.pdf | ENNP用户手册_CN_v3.0.pdf |
| 文档 ID | `2c3c6b66ce9011f18a4cdf41f1d8e4ee` | `01c62d1ccebe11f184dc27e9a0ee1736` |
| Embedding | 通义 `text-embedding-v4` | VLLM `qwen3-text-embedding` |
| 知识库当前 pipeline_id | `47f1dfa4ce8f11f18a4cdf41f1d8e4ee` | 同左 |
| **文档实际 pipeline_id** | 同上 | **NULL** |
| 文档解析任务类型 | `dataflow` | 空字符串，普通解析 |
| 原文切片 / 当前状态 | 164；run=3、progress=1 | 31；run=3、progress=1 |
| 文档级 entity/relation | 345 | 0 |
| 数据集级 entity/relation | 339 | 0 |

当前两库均 `doc_num=1`，数据库中没有昨日开发者手册文档行；它的历史失败操作日志仍存在。未追溯用户删除操作的具体时间和操作者。本轮没有删除文件。

- 91 新应用 `ragflow-app-ragflow-1` healthy，运行 `ragflow-local:v0.27.2-progress-20261023`；92 MySQL、Redis、MinIO、Elasticsearch 均 healthy。
- Redis DB 1 的 `te.0.common`、`te.1.common` 均 `pending=0/lag=0`，Worker 心跳正常、current 为空。因此没有需要再次 ACK 的遗留 Graph 消息。

#### 报错来自视觉模型，Embedding 已成功

`local` 的 PDF 分为 1—12 页和 13—23 页两个普通解析任务：

| 时间（2026-10-23） | 证据 |
|----|----|
| 16:51:25 | 开始普通解析，任务 ID `ee0534d4cebe11f184dc27e9a0ee1736`、`ee05383acebe11f184dc27e9a0ee1736` |
| 16:52:45 | 第一批完成 OCR/表格处理，提示 `Visual model detected`，随后通义 HTTP 400 / `Arrearage` |
| 16:52:49 | 第一批 15 个切片完成 Embedding（0.34 秒）及索引 |
| 16:53:30—31 | 第二批图片理解两次返回同一欠费业务码 |
| 16:53:34—40 | 第二批 16 个切片完成 Embedding（0.29 秒）、索引及任务收尾 |

- 代码调用链：`rag/app/naive.py` 的 PDF 路径 → `deepdoc/parser/figure_parser.py::vision_figure_parser_pdf_wrapper` → 租户默认 `LLMType.VISION` → `rag/app/picture.py::vision_llm_chunk`。
- 视觉模型独立于知识库 Embedding；当前租户的 `img2txt_id/tenant_img2txt_id` 指向通义 `qwen3.8-max`，模型 ID `bbbb69b6ce8811f18a4cdf41f1d8e4ee`。

- `vision_llm_chunk` 捕获异常后回调 `-1` 并返回空描述，普通解析仍继续；`TaskService.update_progress` 明确允许最终 `progress>=1` 覆盖先前 `-1`。所以“文档完成且有 ERROR 日志”在此路径可以同时成立：文字切片写入成功，图片的模型增强描述未成功。
- 它不证明图片理解质量合格，也不是本地向量接口失败。

10 月 24 日从 91 容器复核本地实例：

| 实例 | 地址 | 检查结果 |
|----|----|----|
| Embedding | `http://192.168.88.169:9502/v1` | `/models` HTTP 200，`max_model_len=2048`；`/embeddings` HTTP 200、1024 维 |
| Chat | `http://192.168.88.169:9501/v1` | `/models` HTTP 200，模型 `qwen3-text-generation`、`max_model_len=98304`；本轮未做生成质量测试 |

另有 sklearn `ConvergenceWarning`（重复点导致有效聚类数少于候选聚类数），后续解析与写入已完成，不能将其认定为此次空 Graph 的原因。

#### 为什么当前界面流程相同，实际却未执行 Compiler

核对四处拥有行为的代码：

1.  `api/db/services/file_service.py` 上传新文件时，将知识库的 `pipeline_id` 写入新文档。
2.  `api/apps/services/dataset_api_service.py::update_dataset` 更新知识库本身，没有批量覆盖已有文档的解析配置。
3.  `api/db/services/document_service.py::DocumentService.run` **读取文档自身**的 `pipeline_id`；非空调用 `queue_dataflow`，否则调用 `queue_tasks`。
4.  `api/apps/restful_apis/document_api.py` 的文档更新接口接受显式 `pipeline_id`，通过 `reset_document_for_reparse` 更新文档，并清除旧切片与图片，随后才能重新解析。

- 现场数据与执行日志一致：`local` 文档 `pipeline_id=NULL/parser_id=naive`，没有 `Start knowledge compilation`，只有普通解析的两批任务；`db_t1` 的同名文档有 `dataflow` 和 Compiler 插入 345 条的记录。
- 由此确认两库**实际构建过程不同**。当前快照不足以确认用户在哪个页面、何时切换了知识库默认流程，不将这一操作顺序写成已证实事实。

#### Graph 100% 但为空的完整链路

- `api/apps/services/dataset_api_service.py` 将 Artifacts 的 `graph` 映射为 `structure_graph` 任务，并把 ID 存入 `graphrag_task_id`。
- 该入口负责聚合已编译的文档结构，不会凭普通文本切片自动补做 Compiler 的实体关系抽取。

- `rag/svr/task_executor_refactor/dataset_structure_merger.py::run_structure_merge` 调用 `_collect_structure_pairs`，读取带 `compile_kwd/compilation_template_ids` 的实体记录。
- 没有输入时执行 `progress(1.0, "No doc_graph rows found.")` 并返回。这里的 `doc_graph` 是编译结构数据的称呼，不应误查成 `knowledge_graph_kwd=doc_graph`。

两次实际运行：

| 任务 ID | 时间 | 消息 / 结果 |
|----|----|----|
| `518db9a4cebf11f184dc27e9a0ee1736` | 10-23 16:54:12—16 | `Scanning doc_graph rows...` → `No doc_graph rows found.` |
| `3f2af8facf5811f184dc27e9a0ee1736` | 10-24 11:08:54—55 | 同上；操作日志成功，完成时间 11:08:56 |

ES 的 `ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee` 索引按 KB 过滤：

- `local` 共 33 行：31 条普通切片、2 条 `doc_deleted` 删除标记；`entity/relation/graph` 均为 0。
- `db_t1` 共 850 行：164 条普通切片、345 条 doc scope 实体关系、339 条 dataset scope 实体关系、1 条 graph、1 条删除标记。

这同时排除了“Graph 已存在但前端没显示”和“收尾日志失败未 ACK”作为当前 `local` 空图的解释。先前收尾补丁有效，但不会替代知识编译；重复点击 Graph 不会补齐缺失的输入。

#### 本地模型配置仍未切换完整

- 当前共享 `pipeline_t1` 的 Extractor、Compiler 均指向本地 Chat `4c01e862cebe11f184dc27e9a0ee1736`，但 **Parser 的 `setups.pdf.vlm.llm_id` 仍指向通义 `bbbb69b6ce8811f18a4cdf41f1d8e4ee`**。
- Spreadsheet、Markdown、Doc、Docx 等也保留通义 VLM 配置。租户默认 Chat、Vision 及库的 `parser_config.llm_id` 仍为通义；本地 Chat 在注册表中类型为 1（Chat），不能据名称将其当作已验证的视觉模型。

- 因此只给已有文档补绑流程仍可能再次触发欠费视觉调用。`rag/flow/parser/utils.py::enhance_media_sections_with_vision` 在指定 VLM 解析失败时会回退租户默认视觉模型；**清空节点 VLM 不等于禁用视觉增强**。
- `flatten_media_to_text` 会改变媒体处理和信息保留方式，本轮没有将其作为未经评估的关错开关。

#### 恢复顺序与验收条件（本轮未执行数据重建）

1.  为 `local` 明确完整模型配置：Embedding 保留已验证本地模型；Extractor/Compiler 使用本地 Chat；图片理解应选择实际支持图片输入、已验证可用的本地 VLM。若不需要图片理解，应明确接受的信息损失并单独设计禁用方式，不把纯文本 Chat 填入 VLM。
2.  两库目前引用同一个流程 ID，修改它会影响之后两库的运行。需要保留 `db_t1` 配置时，应为本地流程保存独立副本，再核对 Compiler 模板组 `22f6f8c4ce8f11f18a4cdf41f1d8e4ee` 中包含目标图谱模板。
3.  通过文档解析配置或版本实际支持的文档更新 API，将 **现有文档**绑定到选定流程。单改知识库默认值后直接重跑仍会读取文档旧值。文档接口的 `reset_document_for_reparse` 会删除该文档旧切片/图片，先保留原文件及备份，再执行重建；不要用 SQL 强改状态绕过清理。
4.  先用 23 页用户手册验收：任务类型为 `dataflow`，节点依次执行，Compiler 有非零输出，Indexer 使用本地 Embedding 成功写入，文档 `run=3/progress=1`，日志无欠费调用。再检查 doc scope 的实体/关系和模板 ID。
5.  随后运行 Artifacts Graph，应出现 `Built N/N dataset graph(s)`，且 dataset scope 实体关系非零、界面有节点和边。还要核对来源文档、操作日志、完成时间和队列；不能只验收 100%。
6.  抽样检索和图谱内容质量通过后，再扩大文件范围。两种模型的向量虽均为 1024 维，仍不能混写向量空间；旧库迁移需统一重建。

#### 可复现的只读检查

先按[任务检查步骤](operations.md#task-inspect)运行检查工具，使用本次文档 ID：

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh into app
python /opt/ragflow-ops/inspect_task.py \
  --doc-id 01c62d1ccebe11f184dc27e9a0ee1736
exit
```

在 92 的 `rag_flow` 数据库执行（凭据沿用部署配置，不写入命令记录）：

```sql
START TRANSACTION READ ONLY;
SELECT k.name, k.embd_id, k.tenant_embd_id,
       k.pipeline_id AS kb_pipeline, d.pipeline_id AS doc_pipeline,
       d.parser_id, d.id, d.run, d.progress, d.chunk_num
FROM knowledgebase k JOIN document d ON d.kb_id=k.id
WHERE k.name IN ('db_t1','local');

SELECT t.id,t.task_type,t.progress,t.progress_msg
FROM task t
WHERE t.doc_id='01c62d1ccebe11f184dc27e9a0ee1736'
   OR t.id IN ('518db9a4cebf11f184dc27e9a0ee1736',
               '3f2af8facf5811f184dc27e9a0ee1736');

SELECT id,llm_id,tenant_llm_id,img2txt_id,tenant_img2txt_id
FROM tenant WHERE id='514a9b36ce8511f18a4cdf41f1d8e4ee';
ROLLBACK;
```

在 Kibana Dev Tools 按 KB 统计；将 `kb_id` 替换为上表另一库即可对照：

```text
GET ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee/_search
{
  "size": 0,
  "query": {"term": {"kb_id": "5ef3b38ecea911f18a4cdf41f1d8e4ee"}},
  "aggs": {
    "kind": {"terms": {"field": "knowledge_graph_kwd", "missing": "raw", "size": 30}},
    "scope": {"terms": {"field": "scope_kwd", "missing": "none", "size": 10}}
  }
}
```

历史本地私有证据目录为 `docker/evidence/`，本次未复验文件：

- `current-20261024.json`：两库快照。
- `local-task-20261024.json`：队列与心跳。
- `models-20261024.json`：节点及本地接口检查。
- `worker-summary-20261024.json`：执行日志摘要。
- `hashes-91.json/92.json/container.json`：各端哈希。
- `container-tests-20261024.txt`：容器测试记录。
- 不包含 API Key；文件名、模型配置和运行日志仍应按内部材料管理，目录已被 Git 和 Docker 构建上下文忽略。

<a id="v0272-review"></a>

### 2. 现有 Python 补丁有效性审查

- **2026-11-12 静态核对：**四类补丁和测试仍存在；`build_patch.sh` 已不存在，现行发布按 [源码构建流程](operations.md#source-build)。完成时间更新仍是“先读任务引用、再按 KB ID 更新”，并发竞态仍未封闭。
- 历史 33 项结果不是本次测试结果。

#### 基线与逐文件结论

- 原审查记录的本地、91、92 HEAD 为 tag `v0.27.2` 对应的 `a024bea0cd93f39e6652a42bf84dd20c55bc560b`。该值只标识 10 月 24 日基线；
- 重新比对须使用 `git show a024bea0cd93f39e6652a42bf84dd20c55bc560b:<path>`，不能用当前 `HEAD` 代替。原记录检查范围为当时 `api/deepdoc/rag/test` 的工作区改动及调用链。

| 文件 / 修改 | 解决的问题 | 结论与边界 |
|----|----|----|
| `api/db/__init__.py` 删除重复类型集合 | 旧集合遗漏 StructureGraph 等类型，与 `common.constants` 不一致 | 有效；仓库消费者已统一，无残留导入旧集合 |
| `api/db/services/pipeline_operation_log_service.py` 改用统一集合 | Graph 完成时写操作日志抛 `Invalid task type` | 有效；当前 local 两次操作日志均正常 |
| 同文件按 KB 实际 task_id 选择完成字段 | `graph` 入口与显式 `structure_graph` 入口共用任务类型但存入不同字段 | 有效；新任务引用已存在时可跳过旧任务；并发窗口尚未完全封闭，见下文“仍需处理的代码边界” |
| `rag/svr/task_executor.py` 隔离收尾日志异常 | 日志异常跳过 ACK，留下已完成但 pending 的消息 | 有效；成功/失败均确认已处理消息，执行器 CancelledError 不确认未完成任务；不保证日志失败时日志自动补写 |
| `rag/flow/pipeline.py` 以实例状态累计节点进度 | Redis 轨迹过期丢失已完成节点；无文本回调不更新；重复节点重复累计 | 有效；缓存不再是进度的唯一来源；不是 OCR 断点恢复或剩余时间估计 |
| 同文件删除注释代码 | 过时的同步/异步调用备选分支 | 合理清理，无运行行为变化 |
| `deepdoc/parser/pdf_parser.py` 增加 OCR、逐表及批内进度回调 | 长 PDF 的批内静默，无法观察正在处理的页段和表格 | 有效；保留 50 页窗口、旋转判断和坐标算法；不构成已验证的算法加速 |
| `test/unit_test/rag/flow/test_pipeline_progress.py`（7 项） | 缓存过期/不可用、纯数字、乱序、失败、取消、完成 | 有针对性；使用 stub，不是全流程/模型质量验收 |
| `test/unit_test/api/db/services/test_graph_operation_completion.py`（9 项） | 新类型、入口字段映射、读取时已有更新任务 | 有针对性；没有测试读写之间并发替换 task_id |
| `test/unit_test/rag/svr/test_task_executor_finalization.py`（4 项） | 日志失败 ACK、执行失败、执行器取消 | 有针对性；AST 载入真实 handler，依赖为 mock，不覆盖 Redis 网络失败 |
| `test/unit_test/deepdoc/parser/test_pdf_parser_table_coordinates.py`（13 项） | 既有旋转坐标、增加表格回调及三批页段进度 | 有效；新增回调断言不应被描述为本轮修复了旧坐标算法 |

历史附带核对：当时 `.dockerignore` 排除分离部署凭据/日志/备份/证据；旧补丁构建脚本与 Dockerfile 的五文件范围一致。当前旧脚本已移除，应按现行构建入口操作。根 `CLAUDE.md` 和 Go testdata 的不可读链接为既有工作区情况，本次未改写。

#### 测试及部署一致性证据

- 统一 CRLF/LF 后，5 个 Python 运行文件与 4 个测试文件在本地、91、92 的 SHA-256 全部相同；当前应用容器的 5 个运行文件也相同。生产镜像不包含这 4 个测试文件，不把“镜像中没测试”误报为源码不一致。
- 本地 Python 3.14：当时部署手册中的 4 文件命令，**33 passed**。
- Python 3.13 补丁镜像：生产容器未安装 pytest；使用相同镜像启动 `--rm --network none` 的隔离容器，挂载此前准备的 `/tmp/ragflow-patch-tests/pytest-runtime` 只读测试依赖，在临时目录复制源码及测试，**33 passed**。3 条 `p1` 未注册警告来自临时目录未使用仓库 pytest 配置，不是测试失败；未向生产容器安装包。
- 官方基线实验在本地私有 `evidence/baseline/` 副本进行，未覆盖工作区或服务器源码。相同 33 项检查为 **21 failed / 12 passed**；测试假模块额外提供了从原 `api/db/__init__.py` 提取的旧类型集合，以避免把导入桩缺项误判成业务失败。
- 基线失败拆分：Pipeline 7 项、Graph 9 项、日志失败 ACK 1 项、PDF 4 项。PDF 的 3 项是原方法不接受新增 callback 参数，1 项是原批内没有回调；因此该数字不能解释为“发现 21 个独立 bug”。
- 再仅为基线副本统一类型来源，Graph 检查变为 **3 failed / 6 passed**：`graphrag_task_finish_at`、`mindmap_task_finish_at` 字段写错，以及旧任务仍更新字段。说明完成字段补丁并非冗余。

上述验证足以支持保留现有补丁；不代替真实 PDF 内容质量、数据库并发或完整本地 Compiler → Graph 验收。

#### 仍需处理的代码边界

- **P2：完成时间写入仍有并发竞态。** `PipelineOperationLogService.create` 在读取 KB 的任务引用后，调用 `KnowledgebaseService.update_by_id`；后者 SQL 仅以 KB ID 为条件。
- 如果新 Graph 在两步之间更新 `graphrag_task_id`，旧任务仍可能将其完成时间写入新任务对应字段。当前补丁防住的是“读取时已经换成新任务”，不是原子防护。
- 建议在所属数据访问层使用 `WHERE kb_id=... AND <task_id_field>=finished_task_id` 的条件更新，并补充交错执行测试。本轮没有现场并发触发证据；不要将它说成此次空图的根因。

- **官方 Graph 合并器的成功状态不保证产物成功。** 除无输入按 100% 结束外，`run_structure_merge` 的 Embedding 绑定异常分支也写 100%；逐模板构建捕获异常后最后仍写 `Built rebuilt/total` 的 100%。
- `_collect_structure_pairs` 的查询异常会直接退出扫描，可能被解释成空输入。这些路径都已存在于基线，本地补丁未修改它们。后续应区分空输入、真实异常和成功，并让执行失败进入失败终态。本次已通过独立 ES 查询确认 `local` 实际无编译记录，没有证据证明它触发了这些异常分支。

- **视觉增强失败与最终成功的语义仍需明确。** 当前普通解析允许图片理解失败后完成文本入库；对训练数据制作或评测，必须另验媒体描述覆盖率，不能仅筛选 `run=3`。Pipeline 补丁的失败状态保留只作用于该实例回调；
- 底层 TaskService 仍允许最终 1 覆盖 -1，不应将单元测试结论扩展成全系统不可恢复终态保证。

本轮结论是保留有证据支持的改动，记录上述未覆盖边界。没有以修复配置问题为由增加 vLLM 特判、跳过 Compiler、强制生成成功状态或移除有效测试；也没有改动现有模型配置、重建知识库或发布新的运行镜像。

<a id="date-2026-10-23"></a>

## 2026-10-23

<a id="split-deployment"></a>

### 1. 应用与存储分离部署（摘要档案）

- **摘要所载：**建立独立应用/存储项目；摘要称完成健康、读写、持久化及部分备份恢复验证，未完成压测及完整灾备演练。
- **证据缺口：**仅存 `update.md` 更新摘要；原记录没有完整排查、原始日志和详细验收证据，本次未补造历史结果。
- **再次处理：**使用 [现行部署流程](operations.md#deploy)，记录实际版本、配置备份、执行命令、验收和回退。

<a id="name-history"></a>

### 2. 工程一致性与 Name 历史候选（摘要档案）

- **摘要所载：**核对三端源码与链接；当时证据支持 Compilation 名称候选来自浏览器表单历史，建议用新浏览器配置或清理自动填充复核，未修改业务数据。
- **证据缺口：**仅存 `update.md` 更新摘要；原记录没有完整排查、原始日志和详细验收证据，本次未补造历史结果。
- **再次处理：**使用新的浏览器配置复核名称候选，核对页面字段与请求内容；不要直接修改业务名称。源码核对使用 [清单流程](operations.md#source-parity)，保留对照证据。

<a id="pdf-progress"></a>

### 3. PDF 处理停留在 17.33% 的排查

- **2026-11-12 静态核对：**实例内进度累计、PDF 批内回调和 ACK 异常隔离仍在。PDF 页窗口由 `PDF_PARSER_PAGE_BATCH_SIZE` 控制，默认 50。资源配额为当时现场配置，不是当前环境默认值。
- 运行日志保存前会移除 `q_<维度>_vec`，不能把 DSL 快照当完整向量备份。

#### 故障发生时的证据与结论

2026-10-23，知识库 `db_t1` 的两个 PDF 使用同一条 Compilation operator 流程：

| 文件 | 页数 / 大小 | 检查结果 |
|----|----|----|
| ENNP用户手册_CN_v3.0.pdf | 23 页 / 698,289 bytes | 12:13:15 完成，164 个原文切片；文档知识编译报告 inserted=345 |
| ENNP开发者手册_CN_v1.0.pdf | 146 页 / 1,017,783 bytes | 检查时仍在 DeepDOC 解析，界面 17.33%；尚未进入 Compiler |

页数通过读取 MinIO 原文件并使用 PDFium 核验。文件大小接近不代表解析量接近；日志中的 `164 / 164` 是后续处理数量，不是 PDF 页数。

目标文档 ID：`2bfd0516ce9011f18a4cdf41f1d8e4ee`；解析任务 ID：`44d766bcce9011f18a4cdf41f1d8e4ee`；流程 ID：`47f1dfa4ce8f11f18a4cdf41f1d8e4ee`。

#### 实际执行缓慢：CPU 表格识别

| 时间（服务器 Asia/Shanghai） | 证据 |
|----|----|
| 11:17:29 | 开始 PDF 解析；OCR、版面和表格模型均使用 CPU |
| 12:30:52 | `Structured: 50/146 pages` |
| 13:28:58 | `Structured: 100/146 pages` |
| 13:33:19 | 最后 46 页的图像/OCR 阶段完成，耗时约 255 秒，随后继续版面及表格处理 |
| 14:03—14:06 | 持续新增 `Best table orientation` 日志，Worker 心跳正常，任务仍在执行 |

- 本流程使用 DeepDOC，默认每批 50 页，批内不向流程上报细分进度。默认开启 `TABLE_AUTO_ROTATE=true`，每个识别出的表格都尝试 0/90/180/270 四个角度的 OCR。
- 另一文档完成后至 14:06，仍有 251 条方向识别日志，结果均为 0°，说明大量计算花在表格方向判断。

- 应用容器限制为 8 CPU、12 GiB，未挂载 GPU。实测 CPU 约 795%，内存约 7.7 GiB；5 秒内 cgroup `nr_periods` 与 `nr_throttled` 都增加 50，说明持续触及 CPU 配额。`OOMKilled=false`、重启次数为 0，内存事件无 OOM。
- 宿主机虽然已有 swap 占用，但当时 `vmstat` 的 si/so 为 0，不能把历史 swap 占用认定为当前换页瓶颈。

**结论：任务并未失联，主要耗时在 CPU 上的 DeepDOC 表格处理，CPU 配额进一步限制吞吐。没有做关闭方向识别的对照测试，因此不宣称具体加速倍数。**

#### 百分比停留：进度记录过期与单调更新规则叠加

源码链路：

1.  [pdf_parser.py](../deepdoc/parser/pdf_parser.py) 的 `parse_into_bboxes`：默认 50 页一批，整批完成才回调 `Structured: ...`。
2.  [pipeline.py](../rag/flow/pipeline.py) 的 `callback`：按节点数量等权累计各节点进度，节点轨迹保存在 Redis，TTL 为 `60 * 30` 秒。
3.  [task_service.py](../api/db/services/task_service.py) 的 `update_progress`：普通进度只接受更大的值；日志仍可追加。

本流程有 6 个节点。File 完成、Parser 初始随机进度约 0.04 时，显示值为：

```text
(1 + 0.04) / 6 = 17.3333%
```

两次解析回调分别间隔约 73 分钟、58 分钟，都超过 Redis 轨迹的 30 分钟有效期。轨迹过期后，新的计算丢失了 File 已完成的贡献：

```text
完成 50 页：(50 / 146) / 6 = 5.7078%
完成 100 页：(100 / 146) / 6 = 11.4155%
```

两者都小于已存的 17.3333%，所以任务表只追加页数日志，百分比保持旧值。本次查询对应 Redis key 的 TTL 为 `-2`（不存在），`evicted_keys=0`；这与上述代码和时间间隔吻合。初始 0.04 由存储比例及公式反推，原始 Redis 轨迹已经过期。

**17.33% 是流程进度，不是实际已解析页数；不能据此判定死锁。**

#### 排除项及其他日志

- 目标文件已取回，执行器心跳约 3 秒前更新；没有重新启动或 OOM 的证据。
- 另一文件已经完成 Compiler、Embedding 和 ES 写入；13:48:29 创建的 `structure_graph` 任务也于 13:50:25 完成。Graph 已完成不代表第二个文件已纳入图谱，应在所有文件完成后检查覆盖情况。
- 12:03 的 MinIO `BucketAlreadyOwnedByYou` 是并发创建临时桶冲突，代码有重试；后续任务继续并完成。12:09 的 `LoggingWorker error: TimeoutError` 来自 LiteLLM 日志处理。二者均不是当前 146 页文件停在 Parser 的直接证据，但应在重复出现时另行跟踪。
- 初次检查为只读；其后的授权修复、资源调整和队列恢复见下文修复记录。

#### 附带发现：Graph 已完成但队列未确认

Graph 任务 `5f5ddfe2cea511f18a4cdf41f1d8e4ee` 在 task 表中为 100%，日志显示 13:50:25 计算结束，但 14:16 查询 Redis 时仍在 pending，且数据库没有对应的 Graph 操作日志。

- 检查当前容器与源码发现：[pipeline_operation_log_service.py](../api/db/services/pipeline_operation_log_service.py) 从 `api.db` 导入的 `VALID_PIPELINE_TASK_TYPES` 不包含 `StructureGraph`，会在写操作日志时抛出 `ValueError`；
- `common.constants` 中另一份集合却包含该类型。[task_executor.py](../rag/svr/task_executor.py) 在 finally 中记录操作日志，随后才 ACK，前者抛错会跳过 ACK。容器内实测两个集合的成员判断分别为 False / True，与数据库、队列现象一致。

这是独立的收尾缺陷，不是 PDF 在 Parser 阶段缓慢的原因。任务计算完成、操作日志完成、队列 ACK 是三个不同检查点。修复需要统一任务类型，并在确认结果后处理指定消息。当次恢复结果见下文。

#### 资源与代码

- **资源已生效**：新应用 48 GiB 硬上限、8 GiB 软预留、禁用容器 swap；CPU 无硬配额，竞争权重 512。以 cgroup `cpu.max=max 100000`、`memory.max=51539607552`、`memory.swap.max=0` 验收。
- **进度补丁**：数字状态不再依赖日志 TTL；无文字回调也更新进度；乱序回调不回退；失败/取消保留终态。OCR 与逐表方向处理期间增加回调，不修改 50 页窗口或方向识别设置。
- **Graph 补丁**：删除重复的不完整类型集合，使用 `common.constants`；收尾日志异常不阻止已处理任务 ACK，执行器被取消时不 ACK 未完成工作。
- **完成时间补丁**：界面的 `graph` 入口将 `structure_graph` 任务 ID 存在 `graphrag_task_id`，完成时间应写入相应的 `graphrag_task_finish_at`。按当前实际引用的任务 ID 选择字段，避免旧任务覆盖已排队新任务的完成时间。
- **范围**：这是运行期进度修复，不是准确剩余时间估计。节点仍等权，VLM、Transformer、Compiler 等阶段的耗时受模型服务影响。

#### 实际结束状态与补丁发布

开发者手册的时间线如下（Asia/Shanghai）：

| 时间 | 执行结果 |
|----|----|
| 14:29:25 | 完成 146 页结构化 |
| 14:52:19 | 完成 Parser，包括图片/表格 VLM |
| 14:53:01 | 完成 Title Chunker，Transformer 开始处理 1,357 个文本块 |
| 15:27:22 | Compiler 完成：inserted=1051、updated=0、duplicates_dropped=164 |
| 15:27:25 | Indexer 的 Embedding 调用返回 HTTP 400、`Arrearage` |
| 15:27:26 | 文档及解析任务标记失败（run=4、progress=-1）；消息已 ACK，队列 pending=0 |
| 15:44 | 新应用切换至补丁镜像，健康检查四项依赖均正常；CPU 配额及 48 GiB 内存配置生效 |

故障已经从“CPU 解析缓慢和显示停留”推进到独立的模型账号拒绝。`Arrearage` 响应说明服务商要求账号恢复正常账务状态；无需靠重启容器或重复提交文件验证此错误。Compiler 已产生数据不代表原文切片最终索引成功，此时开发者手册 `chunk_num=0`，不能标记处理完成。

- 失败运行的操作日志 ID 为 `32816206ceb311f187a10f8a34a17206`，保存约 12 MiB 的运行 DSL 和各节点输出；
- 另保存了私有日志副本 `docker/logs/failed-pipeline-20261023-dsl.json` 及 `backups/20261023-progress-fix/failed-pipeline-trace.json`。这些文件不提交 Git、不公开粘贴。
- 恢复前核对文件、节点输出和编译索引，不直接清理已有结果。

- 补丁已完成本地与 Python 3.13 镜像内 33 项测试；新运行环境还以临时任务实测真实 MySQL/Redis：删除日志 key 后进度为 16.6667% → 17.3333% → 22.3744% → 28.0822% → 33.3333%，所有节点完成后为 100%。
- 临时任务不入队，验证结束清理测试行与 key，没有修改用户文档进度。

#### Embedding 拒绝与切换恢复

1.  先区分错误码。401/403 排查密钥和权限；429 排查速率/配额；本次 HTTP 400 的具体业务码为 `Arrearage`，按账号状态处理，不能笼统归为网络或进度错误。
2.  若恢复原模型服务，先做一次小输入验证，再按运行日志核对恢复位置。运行日志中的 DSL 可用于定位已完成节点，但界面的 rerun 接口会删除该文档已有索引；不能未检查就从 Indexer 重跑，否则可能同时清掉 Compiler 已写入的 Graph 数据。
3.  用户提供了本地替代服务 `http://192.168.88.169:9502/v1/embeddings`，模型 `qwen3-text-embedding`。从 91 实测成功，返回 1024 维。页面配置见 [操作手册的本地 Embedding 配置](operations.md#embedding)。密钥仅填模型实例配置，不入文档和源码。
4.  原模型 `text-embedding-v4` 的已有向量也是 1024 维，但模型不同，不能将新旧向量混合在同一知识库。应先在新知识库验证本地模型，正式迁移须统一重建原文和编译索引，并重新生成数据集 Graph；不要直接更新数据库模型 ID 跳过页面检查。
5.  待两个文档均 `run=3/progress=1`、索引写入完成后，再重新生成数据集 Graph，核验两份文档来源、检索、操作日志、完成时间及 pending=0。

当前已完成资源、代码补丁、镜像部署及旧 Graph 单消息恢复；开发者手册的成功索引与两文件 Graph 覆盖需要模型配置/迁移选择完成后验收，不能把本次发布通过写成文档处理成功。

#### Graph 消息恢复记录

- 本次已完成恢复：任务 `5f5ddfe2cea511f18a4cdf41f1d8e4ee`，消息 `1792734509130-0`；恢复前 ES 有 339 条 dataset scope 实体/关系，操作日志为 0。
- 使用补丁服务补写 1 条成功日志，`graphrag_task_finish_at=2026-10-23 13:50:26`，随后对该消息 ACK=1；未删除 Stream，也未重跑图谱计算。它仍是第二份 PDF 完成前生成的 Graph，不代表已覆盖两份文件。

当次为避免中断解析，使用一次性维护容器运行恢复脚本，复用应用 env，只读挂载生成的 service_conf.yaml 和恢复脚本，另挂载私有证据目录。使用 `--entrypoint python`，避免启动第二套 Worker。

#### 复发时步骤

- 先按[文档任务排查](operations.md#task-troubleshooting)采集任务和资源证据，区分解析缓慢、进度显示停滞及模型失败。
- 若 Graph 已写入但缺少成功日志且消息仍 pending，按[单消息恢复](operations.md#graph-finalize)确认队列、备份、恢复和回读。
