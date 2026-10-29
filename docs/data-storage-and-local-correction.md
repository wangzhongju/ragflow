# 数据存储、更新联动与 t4 局部修正

核查时间：2026-10-27。依据当前部署源码和 t4 实际数据，9 个关键后端文件与本地哈希一致。本次仅只读调查并准备请求体，**没有修改 t4、运行模型或触发重建**。

## 1. 存储分工与关联

应用位于 91；本部署的 MySQL、MinIO、Elasticsearch、Redis 位于 92。不是每个处理步骤对应一个独立数据库。

| 数据 | 实际存储 | 结构及关联 |
| --- | --- | --- |
| 知识库、文档、流程定义 | MySQL `rag_flow.knowledgebase/document/user_canvas` | `document.kb_id → knowledgebase.id`；`document.pipeline_id → user_canvas.id`；库的 `embd_id` 指定编码模型，文档自身的 `pipeline_id` 决定实际流程 |
| 文件元数据、文件与文档关系 | MySQL `file/file2document` | 文件 ID 与 document ID 是不同概念；文件关联表连接两者 |
| 原始 DOCX、图片二进制 | MinIO 对象 | t4 原文件桶是 KB ID，对象键为 `document.location`；图片 chunk 的 `img_id=imagetemps-UUID` 指向桶 `imagetemps`、键 `UUID` |
| Parser、Chunker、Extractor、Tokenizer 中间输出 | 执行期间内存；本次持久化在 MySQL `pipeline_operation_log.dsl` | DSL 内 `components[节点ID].obj.params.outputs[输出名].value`；该 JSONField 物理上是 LongText。输出包括 `json/chunks` 列表、摘要、分词及向量，不是每个节点一张结果表 |
| 最终 chunk、全文检索字段、向量 | Elasticsearch `ragflow_<tenant_id>` | 同一 ES 文档：`_id/id`、`doc_id`、`kb_id`、`content_with_weight`、`content_ltks/content_sm_ltks`、`q_1024_vec`、`img_id`、`chunk_order_int` 等 |
| Compiler 实体、关系、文档图谱快照 | 同一个 ES 索引中的其他文档 | `compile_kwd=hypergraph`；`knowledge_graph_kwd=entity/relation/graph`；实体/关系有 `source_chunk_ids`，关联源 chunk；`compilation_template_ids` 关联 MySQL 编译模板 |
| 知识库级合并图谱 | 同一个 ES 索引，另行生成 | `knowledge_graph_kwd=dataset_graph` 及 `scope_kwd=dataset` 的实体/关系，与文档级图谱分开；t4 此次尚无这些记录 |
| 任务、统计和历史记录 | MySQL `task/document/knowledgebase/pipeline_operation_log` | `task.doc_id`、`task.chunk_ids`；chunk 数量是普通块数量，不等于 ES 总行数 |
| 队列、短期运行轨迹、缓存 | Redis DB 1 | 队列如 `te.0.common/te.1.common`；轨迹键 `<flow_id>-<task_id>-logs`，更新时 TTL 为 30 分钟；不是持久化 chunk 正文库 |

关联主线：`KB → Document → Pipeline/Task/OperationLog → Chunk`；图谱通过 `source_chunk_ids → Chunk.id`，图片通过 `Chunk.img_id → MinIO bucket/object`。这些多数是应用层字段关联，**不存在修改上游记录就自动级联重算的数据库外键触发器**。Parser JSON 项通常没有最终 chunk ID；切块合并后，并非每一项都具有可直接追踪的一对一行级外键。

本部署 ES mapping 实测：

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

## 2. 修改后是否自动联动

| 修改入口 | 切块 | 编码/全文索引 | 文档 Graph | 原文件/上游历史 |
| --- | --- | --- | --- | --- |
| 直接改 MySQL 日志 DSL 或 MinIO 内容 | 不重算 | 不重算 | 不重算 | 只改变直接写入对象 |
| 流程结果页编辑 Parser 输出，未点击重跑 | 不重算，改动仅在页面状态 | 不重算 | 不重算 | 未提交运行请求 |
| Parser 结果点击“从当前步骤重新运行” | 以修改后的 Parser 输出重新切块 | 后续节点及入库重新执行 | 下游存在 Compiler 时重新编译 | 不覆盖原文件 |
| 流程结果页编辑 TokenChunker 输出并重跑 | 保留所提交的整份切块结果，跳过该切块节点 | 下游 Extractor/Compiler/Tokenizer 按流程运行 | 重新编译当前文档 | 不自动回写 Parser 原输出 |
| 最终 chunk 编辑/PATCH 接口 | 保留同一个 chunk ID，不重新划分边界 | 重新编码该块并更新分词字段 | **不更新**实体、关系或图谱 JSON | 不更新 Parser/Chunker 运行快照、MinIO 原文件 |

### 单块接口的确切行为

`PATCH /api/v1/datasets/{kb}/documents/{doc}/chunks/{chunk}` 在 [chunk_api.py](../api/apps/restful_apis/chunk_api.py) 中：

1. 校验库、文档、chunk 归属；保持 chunk ID。
2. 从提交正文生成 `content_ltks/content_sm_ltks`。
3. 用该文档所属库的 Embedding 模型重新编码。t4 非 QA，当前请求是 `0.1 × 文件名向量 + 0.9 × 正文向量`，与 t4 Tokenizer 的权重一致。
4. 更新 ES 同一记录的正文、分词和 `q_1024_vec`；ES 在 refresh 后将新分词用于检索，无需全库重建。

注意：接口不会重新生成摘要、问题、关键词、Graph；现有问题/关键词只有显式提交时才更新。若提交 `questions`，其非空内容可作为编码输入。通用接口也不重放其他流程自定义的字段/权重策略；此处结论已对照 t4 的 `fields=[text]`、文件名权重 0.1。普通 GET chunk 会隐藏向量和分词字段，严格验收要读取 ES。当前 PATCH 没有检查底层 update 返回的布尔值，不能只看 HTTP 200/业务码 0 就断言写入成功，必须回读。

### “从当前步骤重新运行”的实际范围

[rerun_agent](../api/apps/restful_apis/agent_api.py) 会先删除**当前文档**的 ES 记录及旧任务，重置其统计，再以请求 DSL 排队；[Pipeline.run](../rag/flow/pipeline.py) 复用选中节点输出，从它的下游执行。因此这不是单个数组项的增量重跑，也不是后台自动监听字段变化。重跑过程中当前文档会暂时无法完整检索，失败也不会自动回滚。

文档级 Compiler 重新执行后，知识库级合并图谱仍是独立任务。只重新生成 Artifacts Graph 不能替代源 chunk 的重编码，也不能保证修复尚未重新编译的文档实体。

## 3. t4 实际定位

| 对象 | 当前值 |
| --- | --- |
| KB | `3c845f96d1ac11f18715a9a4fa662e3a`，名称 `t4` |
| 文档 | `4ea43b56d1ac11f18715a9a4fa662e3a`，`成都开源计算-初步技术方案模板.docx` |
| 流程 | `83edbb8ad1ab11f18715a9a4fa662e3a`，`model_pip_new` |
| 运行日志 | `a9fc07aed1ac11f1a42b59051324d298` |
| 目标 chunk | `cbae5b080fb2ca3b`，`chunk_order_int=20`（第 21 块） |
| Parser 输出 | `Parser:HipSignsRhyme.outputs.json.value[83].text`（第 84 项） |
| Chunker 输出 | `TokenChunker:PublicBusesYawn.outputs.chunks.value[20].text` |
| 当前正文 | `图1. 迪丽热巴` |
| 目标正文 | `图1. 古力娜扎` |
| Embedding | `qwen3.7-text-embedding-flash`，ID `2156bcce3aa54a19b17567e5ab447421`，实际向量 1024 维 |
| ES 索引 | `ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee` |

t4 目前只有这一个文档：25 个普通 chunk（13 文本、8 表格、4 图片），另有 20 实体、17 关系、1 文档图谱快照，共 63 条 ES 记录。没有库级合并图谱。目标说明是独立文本块；相邻图片块为 `40e88a0317ce6554`，图片对象为 `imagetemps/6eaafd5ed1ac11f1a42b59051324d298`，两块不共享 `img_id`，图谱关系引用二者。

必须检查的图谱影响范围：

| ES ID | 影响 |
| --- | --- |
| `bb5a8b338d7de72c` | 人物实体 `name_kwd=迪丽热巴`，引用目标 chunk |
| `52ff36403a0473fd` | 关系起点、描述含旧姓名，引用说明块和图片块 |
| `44c44bdde187e15d` | `@我是娜扎` 实体的英文描述含 `Dilraba Dilmurat`；只引用图片块，单凭目标 `source_chunk_ids` 会漏掉它 |
| `0a4b64636adca88c` | 汇总图 JSON 中的实体/关系及英文描述仍含旧身份 |

此外，Extractor `Extractor:RedLionsSmash` 的 user prompt 仍是 `要总结的文本：\n[在此处插入文本]`，没有正文变量。目标块 summary 是“您好，您似乎忘记粘贴需要总结的文本了……”；Tokenizer 优先用 summary 做全文分词，所以当前正文与 BM25 文本不一致。向量使用 `fields=[text]`，并非也用该错误摘要。这是本次需一起考虑的索引问题。

## 4. 路线 A：只改一个最终 chunk 和检索索引

适用于暂时只修正正文、向量和 BM25；**Graph 不会随之修复**。若要求图谱也一致，直接采用路线 B，无需先执行 A。

1. 确认文档不在解析、没有并发编辑。备份目标 ES 原始记录（包含向量/分词），以及本节列出的图谱记录和运行 DSL；普通 GET chunk 的返回不包含完整索引字段。
2. 在最终 chunk 编辑入口，将目标块整段改为 `图1. 古力娜扎` 并保存；务必区分流程时间线中的中间结果编辑。
3. 或在本地 PowerShell 通过以下接口提交。令牌用当前 RAGFlow 登录令牌或应用 API Key，**不是阿里云模型密钥**；通过终端安全注入 `$env:RAGFLOW_TOKEN`，不要写入项目文件。

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
  --data-binary '@docker/split/evidence/t4-chunk-patch.json'
```

该 UTF-8 请求文件已经准备好，内容只有 `{"content":"图1. 古力娜扎"}`，尚未提交。手工创建时使用 UTF-8。

4. GET 同一 URL 回读，正文应为新文字，ID 仍为 `cbae5b080fb2ca3b`；ES 回读确认两个分词字段不再是无正文提示，向量仍为 1024 维且已重新生成。等待 ES refresh 后做仅全文检索验收，再做向量检索验收。不要用“整个 t4 搜不到旧名”验收 A，因为 Graph 仍有旧名。
5. 如需回退，维护窗口中将备份的完整 ES 行按原 `_id` 恢复并 refresh；简单 PATCH 回旧正文会再次生成索引，**不会恢复原有错误 summary 分词**，与精确回滚不同。

## 5. 路线 B：跳过解析/切块，重建当前文档下游，包含 Graph

这是当前已有流程能提供的完整一致性修正路径。它复用原来的 25 个切块及图片描述，重新运行 `Extractor → Compiler → Tokenizer → 入库`，不重新执行 File、Parser、TokenChunker，不重新识别四张图片，不处理其他文档。但 **t4 只有一份文档，因此仍会重新编码这 25 个 chunk 并重新编译该文档图谱**；不能称为仅一块的增量更新。后续模型调用会使用账号推理额度。

### 5.1 备份与准备

- 备份本文件所有 63 条 ES 行、关联 MySQL 文档/任务/运行 DSL。此次只读原始快照已保存在本地忽略目录 `docker/split/evidence/t4-snapshot.json`，含向量；进一步的原文件/代码/mapping 核验在 `t4-details.json`。执行前应重新取快照，不能用旧快照覆盖之后的用户修改。
- 确认文档空闲。保存上游结果不改原始 DOCX：MinIO 原文件中仍有一次旧姓名，直接从 File 再解析会恢复旧题注。应另行维护修正后的源文件版本，避免未来重解析覆盖人工修正。
- 本次已根据现场日志生成 `docker/split/evidence/t4-rerun-request.json`，仅作为待审阅请求体，未提交。其修改范围见下表。

| 请求体内位置 | 修正 |
| --- | --- |
| Parser 的 `outputs.json.value[83].text` | 改为新题注，保持此次运行记录上游说明一致 |
| TokenChunker 的 `outputs.json.value[83].text` | 同步其传递的 Parser JSON 副本 |
| TokenChunker 的 `outputs.chunks.value[20].text` | 改为新题注，其他 24 块原样保留 |
| Extractor 的 `params.prompts[0].content` | `要总结的文本：\n{TokenChunker:PublicBusesYawn@chunks}` |
| 顶层 `id` | 当前运行日志 ID，**不是 pipeline ID** |
| 顶层 `component_id` | `TokenChunker:PublicBusesYawn`，复用此节点输出，从 Extractor 开始执行 |

Extractor 会识别此列表变量，并在循环内用各块的 `text` 替换变量值。仅在流程画布修改提示词不会自动更新旧日志 DSL；此次请求已同时修正其运行 DSL。日后从原文件执行仍读取画布配置，需在 `model_pip_new` 中也将正文变量绑定为 TokenChunker 的 chunks（通过变量选择器），避免继续产生无正文摘要。

如果通过 UI 修改：进入该文档的流程结果，选择 TokenChunker，修改第 21 块后点击“从当前步骤重新运行”。但当前 UI 只替换选中节点，不会一并修正旧日志里的 Extractor 提示词，所以本例推荐使用已审阅的完整 DSL 请求，而非直接点击旧运行记录重跑。

### 5.2 提交前核对当前运行记录

```powershell
$base = 'http://192.168.88.91:9380/api/v1'
$kb = '3c845f96d1ac11f18715a9a4fa662e3a'
$log = 'a9fc07aed1ac11f1a42b59051324d298'
if (-not $env:RAGFLOW_TOKEN) { throw '请先设置 RAGFLOW_TOKEN' }
curl.exe --fail-with-body -sS "$base/datasets/$kb/ingestions/$log" `
  -H "Authorization: Bearer $env:RAGFLOW_TOKEN" `
  -o docker/split/evidence/t4-current-log.json
```

确认响应业务码为 0、文档 ID 相符，且 `data.dsl` 与 `t4-snapshot.json` 中该日志的原 DSL 语义一致；同时确认没有更新的解析记录或并发修改。若发生变化，应从最新日志重做上表修正，不能直接提交旧请求体。本次接口没有提供乐观版本冲突检查，维护窗口内完成备份、核对和提交。

### 5.3 提交下游重跑

```powershell
curl.exe --fail-with-body -sS -X POST "$base/agents/rerun" `
  -H "Authorization: Bearer $env:RAGFLOW_TOKEN" `
  -H 'Content-Type: application/json' `
  --data-binary '@docker/split/evidence/t4-rerun-request.json'
```

请求成功只代表排队成功。该接口会先删除目标文档原 ES 数据再运行，不提供在线原子切换；不得截取单个 chunk 作为 `chunks` 列表提交，否则其他 24 块会丢失。不要选择 Tokenizer 为起点：它已经是最后节点，不能因此重新执行 Compiler；也不要选择 Compiler 为起点期待它重算，因为选中节点本身会被跳过。

### 5.4 验收

1. 文档达到 `run=3/progress=1`，新操作日志无错误；确认摘要确实收到正文，不再是请用户提供文本的回复。
2. 普通块仍完整；本例未改切块边界，预期为 25 块。从新结果按精确正文定位新题注，**不要假定旧 chunk ID 继续有效**，Compiler 按正文、文档 ID 和块序号重算 ID。
3. ES 中新题注块正文、全文分词、1024 维向量一致；检查 Graph 关联的 `source_chunk_ids` 均能解析到存在的普通块。
4. 回读文档 Graph：`GET /api/v1/datasets/{kb}/documents/{doc}/structure/graph`，确认新人物实体与关系正确；检查 `迪丽热巴` 和 `Dilraba Dilmurat` 是否仍存在于当前有效实体/关系/图谱 JSON。特别复核 `@我是娜扎` 的描述，不能仅按原目标 chunk ID 查依赖。
5. 图谱是模型重新生成的结果，实体数/关系数可能变化，不能用固定 38 条作为成功标准；必须核对内容，不仅看任务 100%。历史日志和原始 DOCX 仍出现旧名不等于当前索引修正失败。
6. t4 当前没有库级图谱；如需要 Artifacts 下的知识库合并 Graph，再运行 `POST /api/v1/datasets/{kb}/index?type=structure_graph`，并用同 URL 的 GET 查询进度。它是独立的图谱合并任务，不是重新解析源文件；不能先做合并来替代文档 Compiler 的修正。

### 5.5 失败与回退

重跑失败后，先停止/等待该文档任务彻底结束，避免 Worker 覆盖恢复数据。备份失败状态，清理该文档本轮新写入的 ES 行，再按备份 `_id` 恢复完整原行，连同对应 MySQL 文档/任务/运行日志状态及计数一致恢复；只恢复旧题注 chunk 不能恢复原来的 63 条记录。若已经运行了库级合并任务，还要处理其派生结果。此流程不是跨 MySQL/ES/Redis 的事务，未验证的自动 SQL 回滚命令不应直接执行。

若业务要求“只改一块，同时精确修正相关 Graph、原始中间结果和所有派生索引，其他 24 块完全不计算”，当前通用接口没有该能力，需要新增受控局部修正事务：追踪源块版本、使依赖结果失效、重新生成受影响的实体/关系及图谱快照、更新其分词和向量，并处理同义名/英文描述等跨块依赖。不能用多表字符串替换冒充完整级联修复。
