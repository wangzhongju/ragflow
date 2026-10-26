# RAGFlow 文档处理与 Graph 任务排查手册

适用部署：v0.27.2，源码提交 `a024bea0cd93f39e6652a42bf84dd20c55bc560b`；应用在 91，存储在 92。以下命令除特别标注外，均在 **91 的 Bash** 执行。基础启停、备份和数据库连接见 [install.md](install.md)。

**最新复核（2026-10-24）**：`local` 的本地 Embedding 已成功，报错来自通义 VLM；现有文档未绑定知识库当前流程，因此没有 Compiler 输入可供 Graph 聚合。见第 9 节。第 1—8 节保留 10 月 23 日故障与处理历史，不代表当前仍有两份 PDF 待运行。

## 1. 故障发生时的证据与结论

2026-10-23，知识库 `db_t1` 的两个 PDF 使用同一条 Compilation operator 流程：

| 文件 | 页数 / 大小 | 检查结果 |
| --- | --- | --- |
| ENNP用户手册_CN_v3.0.pdf | 23 页 / 698,289 bytes | 12:13:15 完成，164 个原文切片；文档知识编译报告 inserted=345 |
| ENNP开发者手册_CN_v1.0.pdf | 146 页 / 1,017,783 bytes | 检查时仍在 DeepDOC 解析，界面 17.33%；尚未进入 Compiler |

页数通过读取 MinIO 原文件并使用 PDFium 核验。文件大小接近不代表解析量接近；日志中的 `164 / 164` 是后续处理数量，不是 PDF 页数。

目标文档 ID：`2bfd0516ce9011f18a4cdf41f1d8e4ee`；解析任务 ID：`44d766bcce9011f18a4cdf41f1d8e4ee`；流程 ID：`47f1dfa4ce8f11f18a4cdf41f1d8e4ee`。

### 1.1 实际执行缓慢：CPU 表格识别

| 时间（服务器 Asia/Shanghai） | 证据 |
| --- | --- |
| 11:17:29 | 开始 PDF 解析；OCR、版面和表格模型均使用 CPU |
| 12:30:52 | `Structured: 50/146 pages` |
| 13:28:58 | `Structured: 100/146 pages` |
| 13:33:19 | 最后 46 页的图像/OCR 阶段完成，耗时约 255 秒，随后继续版面及表格处理 |
| 14:03—14:06 | 持续新增 `Best table orientation` 日志，Worker 心跳正常，任务仍在执行 |

本流程使用 DeepDOC，默认每批 50 页，批内不向流程上报细分进度。默认开启 `TABLE_AUTO_ROTATE=true`，每个识别出的表格都尝试 0/90/180/270 四个角度的 OCR。另一文档完成后至 14:06，仍有 251 条方向识别日志，结果均为 0°，说明大量计算花在表格方向判断。

应用容器限制为 8 CPU、12 GiB，未挂载 GPU。实测 CPU 约 795%，内存约 7.7 GiB；5 秒内 cgroup `nr_periods` 与 `nr_throttled` 都增加 50，说明持续触及 CPU 配额。`OOMKilled=false`、重启次数为 0，内存事件无 OOM。宿主机虽然已有 swap 占用，但当时 `vmstat` 的 si/so 为 0，不能把历史 swap 占用认定为当前换页瓶颈。

**结论：任务并未失联，主要耗时在 CPU 上的 DeepDOC 表格处理，CPU 配额进一步限制吞吐。没有做关闭方向识别的对照测试，因此不宣称具体加速倍数。**

### 1.2 百分比停留：进度记录过期与单调更新规则叠加

源码链路：

1. [pdf_parser.py](../deepdoc/parser/pdf_parser.py) 的 `parse_into_bboxes`：默认 50 页一批，整批完成才回调 `Structured: ...`。
2. [pipeline.py](../rag/flow/pipeline.py) 的 `callback`：按节点数量等权累计各节点进度，节点轨迹保存在 Redis，TTL 为 `60 * 30` 秒。
3. [task_service.py](../api/db/services/task_service.py) 的 `update_progress`：普通进度只接受更大的值；日志仍可追加。

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

### 1.3 排除项及其他日志

- 目标文件已取回，执行器心跳约 3 秒前更新；没有重新启动或 OOM 的证据。
- 另一文件已经完成 Compiler、Embedding 和 ES 写入；13:48:29 创建的 `structure_graph` 任务也于 13:50:25 完成。Graph 已完成不代表第二个文件已纳入图谱，应在所有文件完成后检查覆盖情况。
- 12:03 的 MinIO `BucketAlreadyOwnedByYou` 是并发创建临时桶冲突，代码有重试；后续任务继续并完成。12:09 的 `LoggingWorker error: TimeoutError` 来自 LiteLLM 日志处理。二者均不是当前 146 页文件停在 Parser 的直接证据，但应在重复出现时另行跟踪。
- 初次检查为只读；其后的授权修复、资源调整和队列恢复见第 8 节。

### 1.4 附带发现：Graph 已完成但队列未确认

Graph 任务 `5f5ddfe2cea511f18a4cdf41f1d8e4ee` 在 task 表中为 100%，日志显示 13:50:25 计算结束，但 14:16 查询 Redis 时仍在 pending，且数据库没有对应的 Graph 操作日志。

检查当前容器与源码发现：[pipeline_operation_log_service.py](../api/db/services/pipeline_operation_log_service.py) 从 `api.db` 导入的 `VALID_PIPELINE_TASK_TYPES` 不包含 `StructureGraph`，会在写操作日志时抛出 `ValueError`；`common.constants` 中另一份集合却包含该类型。[task_executor.py](../rag/svr/task_executor.py) 在 finally 中记录操作日志，随后才 ACK，前者抛错会跳过 ACK。容器内实测两个集合的成员判断分别为 False / True，与数据库、队列现象一致。

这是独立的收尾缺陷，不是 PDF 在 Parser 阶段缓慢的原因。任务计算完成、操作日志完成、队列 ACK 是三个不同检查点。修复需要统一任务类型，并在确认结果后处理指定消息。第 8 节记录已实施的恢复；不能批量 ACK。

## 2. 快速排查入口

```bash
ssh cdky@192.168.88.91
cd /home/cdky/workspace/github/ragflow/docker/split
date -Is
bash ops.sh app ps
curl -fsS http://192.168.88.91:9380/api/v1/system/healthz

# 列出最近 10 个文档，取得目标文档 ID。
bash ops.sh app exec -T ragflow python - < inspect_task.py

# 替换为实际文档 ID。下例为本次问题文件。
DOC_ID=2bfd0516ce9011f18a4cdf41f1d8e4ee
umask 077
mkdir -p evidence
bash ops.sh app exec -T ragflow python - --doc-id "$DOC_ID" \
  < inspect_task.py > "evidence/task-${DOC_ID}-$(date +%Y%m%d-%H%M%S).json"
```

[inspect_task.py](../docker/split/inspect_task.py) 使用容器已有数据库凭据，以只读事务查询文档、任务、流程节点和知识库 Graph 任务，再读取 Redis 心跳、队列和轨迹 TTL。它不提交任务、不消费队列、不调用模型、不输出模型密钥或完整流程提示词。报告包含文件名和任务日志，外发前检查敏感信息。

本部署端口绑定到 LAN IP；在 **91 宿主机**访问 `127.0.0.1:9380` 会失败，应使用上面的 LAN 地址。在容器内部才使用 `127.0.0.1:9380`。

间隔 1—5 分钟再次采集，比较任务日志、Worker 当前任务和底层解析日志。对于批处理，观察窗口需结合已知批次耗时，不能简单以“5 分钟百分比不变”判定失败。

## 3. 先确定停在哪个阶段

| 最新任务消息 | 所在阶段 | 优先检查 |
| --- | --- | --- |
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

如需在 DBeaver 手工核验，连接 92:3306 的 `rag_flow`，执行只读 SQL：

```sql
START TRANSACTION READ ONLY;
SELECT id, name, run, progress, chunk_num, pipeline_id,
       process_begin_at, process_duration, update_date, progress_msg
FROM document
WHERE id = '2bfd0516ce9011f18a4cdf41f1d8e4ee';

SELECT id, doc_id, task_type, progress, retry_count,
       begin_at, update_date, progress_msg
FROM task
WHERE doc_id = '2bfd0516ce9011f18a4cdf41f1d8e4ee'
ORDER BY create_time DESC;
ROLLBACK;
```

不要直接修改 progress/run 制造“完成”，也不要删除任务行、Redis stream 或原文件来解卡。

## 4. 日志与资源检查

### 4.1 找到当前执行器日志

```bash
ls -lt logs/task_executor*.log
bash ops.sh app logs --since 30m --tail 150 ragflow

# 从报告 workers.name 选择当前执行器，不要只看部署前的旧日志。
LOG=logs/task_executor_common_6be828c870c6_0.log
TASK_ID=44d766bcce9011f18a4cdf41f1d8e4ee

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

有些 DeepDOC 日志没有 task_id，同一个 Worker 也可能同时处理多个文档。需结合任务开始/结束时间、心跳 current_task_ids 和阶段判断归属；不能把任意一条日志都归到目标任务。任务中的 `Structured` 消息可能仅写入数据库，而未出现在 Worker 文本日志。

搜索 ERROR 时限定日志行前缀，避免把提示词、文档正文中的 ERROR 字样误判为执行异常。先读取异常类型及前后上下文，再检查该任务是否继续推进或已完成。

### 4.2 检查容器配额和真实消耗

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
bash ops.sh app exec -T ragflow python - <<'PY'
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
```

`cpu.max=800000 100000` 表示 8 核配额。比较两次 `nr_throttled` 与 `nr_periods` 增量；两者接近说明多数调度周期触及限额。`throttled_usec` 可累计多个线程的等待，不能直接当作任务剩余时间。`memory.events` 中 oom/oom_kill 非零时，结合容器启动时间和日志排查内存问题。

### 4.3 核验 PDF 页数

下面使用本部署的 MinIO 配置和 `DOC_ID` 读取原文件，仅统计页数，不触发 OCR 或模型请求。文件会读入容器内存，大文件应先检查剩余内存。

```bash
bash ops.sh app exec -T -e DOC_ID="$DOC_ID" ragflow python - <<'PY'
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
```

## 5. 队列、缓存和存储检查

### 5.1 Redis：区分待领取、执行中和记录过期

查看诊断报告中的 `workers`、`queues`、`pipeline_log_ttl`：

- `lag` 表示尚未投递给消费者的条目；`pending` 是已投递但尚未 ACK 的条目，正常长任务也会 pending。
- 心跳新、目标任务在 `current_task_ids`、底层日志增加：优先判断执行缓慢。
- 心跳过期、任务长期 pending：核查执行器进程和异常退出，不能仅凭 pending 数量强行 ACK。
- `pending_sample` 只读展示各队列最前面的至多 10 条 pending；`known_task_progress=1` 仍 pending 时，检查操作日志和 ACK 收尾。样本中没有目标消息不代表整个队列没有它。
- TTL 正数为剩余秒数，`-2` 为 key 不存在，`-1` 为没有过期时间。缺失轨迹不等于任务被删除。
- `expired_keys` 是实例累计值，不能单独证明某个 key 过期；应结合目标 TTL、源码设置和回调间隔。
- 本部署使用 Redis DB **1**，队列为 `te.0.common` / `te.1.common`。在 Redis Insight 查看时选对 DB；不要执行 FLUSHDB/FLUSHALL。

### 5.2 存储服务

在 **92** 执行：

```bash
cd /home/cdky/workspace/github/ragflow/docker/split
bash ops.sh storage ps
bash ops.sh storage logs --since 30m --tail 100 mysql redis elasticsearch minio
df -h / /home
```

结合 91 的 `/api/v1/system/healthz` 检查跨机访问。MinIO 只验证服务存活还不够，必要时在 Console 核对目标对象存在、大小和下载能力；ES 写入异常则在 Kibana 检查集群、索引与磁盘水位。具体连接、鉴权命令见 [install.md](install.md)，不要将 app.env/storage.env 的内容粘贴到工单。

## 6. 按原因选择处理方式

| 确认的原因 | 处理方式 | 验证重点 |
| --- | --- | --- |
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

环境参数需进入新应用容器才生效，修改文件不会改变正在执行的 Parser；`docker compose restart` 也不会加载新的容器环境。调整后通常需要重建新应用容器，会中断当前工作，安排在任务结束后的维护窗口，具体命令见部署手册第 9 节。资源上限可以在线更新，代码切换仍需重建进程。

本次补丁将运行中节点的数字进度保存在 Pipeline 实例，Redis 仅保留 UI 轨迹，并增加批内回调；任务进程重启后仍需依照现有任务重试机制重新执行，补丁不提供 OCR 断点恢复。镜像构建及测试命令见部署手册第 9 节。

## 7. 恢复验收与证据归档

1. 重新运行 `inspect_task.py --doc-id`，确认文档 `run=3`、`progress=1`，关联解析任务完成，日志包含最终写入成功。
2. 检查切片数量及抽样内容，尤其是表格、图片、跨页段落；状态完成不等于解析质量合格。
3. 检查 Compiler 成功记录及 Graph 中的来源文档。已有数据集 Graph 可能是在第二个文件完成前生成，需要根据界面支持的操作重新生成并核验覆盖范围。
4. 检查后续查询/检索能命中目标文档；如做模型效果测试，记录模型、参数、耗时和费用。
5. 保存故障前后诊断 JSON、关键日志时间段、版本、配置变更及验证结果；[update.md](update.md) 只记录问题、原因、处理和结果，详细命令保留在本手册。

初次只读复核截止 2026-10-23 14:20，当时仍处于 Parser；后续处理状态见下面的修复记录。证据存放在 `docker/split/evidence/`，不提交 Git。

## 8. 已授权修复与单任务恢复流程

### 8.1 资源与代码

- **资源已生效**：新应用 48 GiB 硬上限、8 GiB 软预留、禁用容器 swap；CPU 无硬配额，竞争权重 512。以 cgroup `cpu.max=max 100000`、`memory.max=51539607552`、`memory.swap.max=0` 验收。
- **进度补丁**：数字状态不再依赖日志 TTL；无文字回调也更新进度；乱序回调不回退；失败/取消保留终态。OCR 与逐表方向处理期间增加回调，不修改 50 页窗口或方向识别设置。
- **Graph 补丁**：删除重复的不完整类型集合，使用 `common.constants`；收尾日志异常不阻止已处理任务 ACK，执行器被取消时不 ACK 未完成工作。
- **完成时间补丁**：界面的 `graph` 入口将 `structure_graph` 任务 ID 存在 `graphrag_task_id`，完成时间应写入相应的 `graphrag_task_finish_at`。按当前实际引用的任务 ID 选择字段，避免旧任务覆盖已排队新任务的完成时间。
- **范围**：这是运行期进度修复，不是准确剩余时间估计。节点仍等权，VLM、Transformer、Compiler 等阶段的耗时受模型服务影响。

### 8.2 Graph 已完成但未 ACK 的恢复

只处理已有结果的单个 `structure_graph` 成功任务。先确认 `task.progress=1`、近期 Worker 的 current 不再包含该任务、ES 有对应数据集实体/关系记录，并备份 MySQL。不要将以下办法用于仍运行、失败或没有索引结果的任务。

本次已完成恢复：任务 `5f5ddfe2cea511f18a4cdf41f1d8e4ee`，消息 `1792734509130-0`；恢复前 ES 有 339 条 dataset scope 实体/关系，操作日志为 0。使用补丁服务补写 1 条成功日志，`graphrag_task_finish_at=2026-10-23 13:50:26`，随后对该消息 ACK=1；未删除 Stream，也未重跑图谱计算。它仍是第二份 PDF 完成前生成的 Graph，不代表已覆盖两份文件。

工具 `docker/split/finalize_graph.py` 默认只检查；`--apply` 才补日志并 ACK。它校验任务类型、任务进度、数据集引用、参与文档、近期执行器、ES 索引以及成功日志；只确认指定消息。传入一个新的私有 `--backup` 路径保存队列原文和任务信息，已有同名文件时拒绝覆盖。操作日志用数据集、类型和任务开始时间定位；不要并发运行恢复命令。

在已切换补丁镜像的 **91** 执行：

```bash
cd /home/cdky/workspace/github/ragflow/docker/split
TASK_ID=待恢复的任务ID
DATASET_ID=对应知识库ID
MESSAGE_ID=该任务的精确Redis消息ID
# 只检查：输出应确认 progress=1、有 dataset_graph_rows
bash ops.sh app exec -T ragflow python - \
  --task-id "$TASK_ID" --dataset-id "$DATASET_ID" --message-id "$MESSAGE_ID" \
  < finalize_graph.py
# 先按 install.md 第 6 节在 92 备份 MySQL，再执行单消息恢复
# /ragflow/logs 为宿主持久化目录；恢复证据按 600 权限保存
bash ops.sh app exec -T ragflow python - \
  --task-id "$TASK_ID" --dataset-id "$DATASET_ID" --message-id "$MESSAGE_ID" \
  --apply --backup "/ragflow/logs/graph-recovery-${TASK_ID}-$(date +%s).json" \
  < finalize_graph.py
```

若旧执行器尚有长任务不能重启，可用补丁镜像启动**一次性维护容器**：复用 `app.env`、只读挂载当前容器生成的 `conf/service_conf.yaml`、挂载恢复脚本和私有证据目录，使用 `--entrypoint python` 运行同一脚本。不要通过入口脚本启动第二套 Worker；维护容器只调用收尾服务，没有模型调用。此次采用该方式，保留正在解析的 PDF。

任何检查失败都先停止恢复并调查，不用 SQL 强改 `progress=1` 绕过检查。ACK 成功后再次运行只读检查，应 `pending=false`、`operation_logs=1`；再核对 KB 完成时间及界面 Graph 内容。

### 8.3 实际结束状态与补丁发布

开发者手册的时间线如下（Asia/Shanghai）：

| 时间 | 执行结果 |
| --- | --- |
| 14:29:25 | 完成 146 页结构化 |
| 14:52:19 | 完成 Parser，包括图片/表格 VLM |
| 14:53:01 | 完成 Title Chunker，Transformer 开始处理 1,357 个文本块 |
| 15:27:22 | Compiler 完成：inserted=1051、updated=0、duplicates_dropped=164 |
| 15:27:25 | Indexer 的 Embedding 调用返回 HTTP 400、`Arrearage` |
| 15:27:26 | 文档及解析任务标记失败（run=4、progress=-1）；消息已 ACK，队列 pending=0 |
| 15:44 | 新应用切换至补丁镜像，健康检查四项依赖均正常；CPU 配额及 48 GiB 内存配置生效 |

故障已经从“CPU 解析缓慢和显示停留”推进到独立的模型账号拒绝。`Arrearage` 响应说明服务商要求账号恢复正常账务状态；无需靠重启容器或重复提交文件验证此错误。Compiler 已产生数据不代表原文切片最终索引成功，此时开发者手册 `chunk_num=0`，不能标记处理完成。

失败运行的操作日志 ID 为 `32816206ceb311f187a10f8a34a17206`，保存约 12 MiB 的运行 DSL 和各节点输出；另保存了私有日志副本 `docker/split/logs/failed-pipeline-20261023-dsl.json` 及 `backups/20261023-progress-fix/failed-pipeline-trace.json`。这些文件不提交 Git、不公开粘贴。恢复前核对文件、节点输出和编译索引，不直接清理已有结果。

补丁已完成本地与 Python 3.13 镜像内 33 项测试；新运行环境还以临时任务实测真实 MySQL/Redis：删除日志 key 后进度为 16.6667% → 17.3333% → 22.3744% → 28.0822% → 33.3333%，所有节点完成后为 100%。临时任务不入队，验证结束清理测试行与 key，没有修改用户文档进度。

### 8.4 Embedding 拒绝与切换恢复

1. 先区分错误码。401/403 排查密钥和权限；429 排查速率/配额；本次 HTTP 400 的具体业务码为 `Arrearage`，按账号状态处理，不能笼统归为网络或进度错误。
2. 若恢复原模型服务，先做一次小输入验证，再按运行日志核对恢复位置。运行日志中的 DSL 可用于定位已完成节点，但界面的 rerun 接口会删除该文档已有索引；不能未检查就从 Indexer 重跑，否则可能同时清掉 Compiler 已写入的 Graph 数据。
3. 用户提供了本地替代服务 `http://192.168.88.169:9502/v1/embeddings`，模型 `qwen3-text-embedding`。从 91 实测成功，返回 1024 维。页面配置见 [install.md 第 10 节](install.md#10-本地-qwen3-embedding-页面配置)。密钥仅填模型实例配置，不入文档和源码。
4. 原模型 `text-embedding-v4` 的已有向量也是 1024 维，但模型不同，不能将新旧向量混合在同一知识库。应先在新知识库验证本地模型，正式迁移须统一重建原文和编译索引，并重新生成数据集 Graph；不要直接更新数据库模型 ID 跳过页面检查。
5. 待两个文档均 `run=3/progress=1`、索引写入完成后，再重新生成数据集 Graph，核验两份文档来源、检索、操作日志、完成时间及 pending=0。

当前已完成资源、代码补丁、镜像部署及旧 Graph 单消息恢复；开发者手册的成功索引与两文件 Graph 覆盖需要模型配置/迁移选择完成后验收，不能把本次发布通过写成文档处理成功。

## 9. 2026-10-24：local 报错与空 Graph

### 9.1 排查范围与当前状态

本轮于 11:38 起从 91 应用读取 92 的 MySQL、Redis、Elasticsearch，并检查两台服务器源码及 91 当前补丁容器。查询不修改业务数据；另从应用容器向本地 Embedding 发出一次合成短文本请求（8 tokens），未重试欠费通义服务。时间均为 Asia/Shanghai。

| 项目 | db_t1 | local |
| --- | --- | --- |
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

91 新应用 `ragflow-app-ragflow-1` healthy，运行 `ragflow-local:v0.27.2-progress-20261023`；92 MySQL、Redis、MinIO、Elasticsearch 均 healthy。Redis DB 1 的 `te.0.common`、`te.1.common` 均 `pending=0/lag=0`，Worker 心跳正常、current 为空。因此没有需要再次 ACK 的遗留 Graph 消息。

### 9.2 报错来自视觉模型，Embedding 已成功

`local` 的 PDF 分为 1—12 页和 13—23 页两个普通解析任务：

| 时间（2026-10-23） | 证据 |
| --- | --- |
| 16:51:25 | 开始普通解析，任务 ID `ee0534d4cebe11f184dc27e9a0ee1736`、`ee05383acebe11f184dc27e9a0ee1736` |
| 16:52:45 | 第一批完成 OCR/表格处理，提示 `Visual model detected`，随后通义 HTTP 400 / `Arrearage` |
| 16:52:49 | 第一批 15 个切片完成 Embedding（0.34 秒）及索引 |
| 16:53:30—31 | 第二批图片理解两次返回同一欠费业务码 |
| 16:53:34—40 | 第二批 16 个切片完成 Embedding（0.29 秒）、索引及任务收尾 |

代码调用链：`rag/app/naive.py` 的 PDF 路径 → `deepdoc/parser/figure_parser.py::vision_figure_parser_pdf_wrapper` → 租户默认 `LLMType.VISION` → `rag/app/picture.py::vision_llm_chunk`。视觉模型独立于知识库 Embedding；当前租户的 `img2txt_id/tenant_img2txt_id` 指向通义 `qwen3.8-max`，模型 ID `bbbb69b6ce8811f18a4cdf41f1d8e4ee`。

`vision_llm_chunk` 捕获异常后回调 `-1` 并返回空描述，普通解析仍继续；`TaskService.update_progress` 明确允许最终 `progress>=1` 覆盖先前 `-1`。所以“文档完成且有 ERROR 日志”在此路径可以同时成立：文字切片写入成功，图片的模型增强描述未成功。它不证明图片理解质量合格，也不是本地向量接口失败。

10 月 24 日从 91 容器复核本地实例：

| 实例 | 地址 | 检查结果 |
| --- | --- | --- |
| Embedding | `http://192.168.88.169:9502/v1` | `/models` HTTP 200，`max_model_len=2048`；`/embeddings` HTTP 200、1024 维 |
| Chat | `http://192.168.88.169:9501/v1` | `/models` HTTP 200，模型 `qwen3-text-generation`、`max_model_len=98304`；本轮未做生成质量测试 |

另有 sklearn `ConvergenceWarning`（重复点导致有效聚类数少于候选聚类数），后续解析与写入已完成，不能将其认定为此次空 Graph 的原因。

### 9.3 为什么当前界面流程相同，实际却未执行 Compiler

核对四处拥有行为的代码：

1. `api/db/services/file_service.py` 上传新文件时，将知识库的 `pipeline_id` 写入新文档。
2. `api/apps/services/dataset_api_service.py::update_dataset` 更新知识库本身，没有批量覆盖已有文档的解析配置。
3. `api/db/services/document_service.py::DocumentService.run` **读取文档自身**的 `pipeline_id`；非空调用 `queue_dataflow`，否则调用 `queue_tasks`。
4. `api/apps/restful_apis/document_api.py` 的文档更新接口接受显式 `pipeline_id`，通过 `reset_document_for_reparse` 更新文档，并清除旧切片与图片，随后才能重新解析。

现场数据与执行日志一致：`local` 文档 `pipeline_id=NULL/parser_id=naive`，没有 `Start knowledge compilation`，只有普通解析的两批任务；`db_t1` 的同名文档有 `dataflow` 和 Compiler 插入 345 条的记录。由此确认两库**实际构建过程不同**。当前快照不足以确认用户在哪个页面、何时切换了知识库默认流程，不将这一操作顺序写成已证实事实。

### 9.4 Graph 100% 但为空的完整链路

`api/apps/services/dataset_api_service.py` 将 Artifacts 的 `graph` 映射为 `structure_graph` 任务，并把 ID 存入 `graphrag_task_id`。该入口负责聚合已编译的文档结构，不会凭普通文本切片自动补做 Compiler 的实体关系抽取。

`rag/svr/task_executor_refactor/dataset_structure_merger.py::run_structure_merge` 调用 `_collect_structure_pairs`，读取带 `compile_kwd/compilation_template_ids` 的实体记录。没有输入时执行 `progress(1.0, "No doc_graph rows found.")` 并返回。这里的 `doc_graph` 是编译结构数据的称呼，不应误查成 `knowledge_graph_kwd=doc_graph`。

两次实际运行：

| 任务 ID | 时间 | 消息 / 结果 |
| --- | --- | --- |
| `518db9a4cebf11f184dc27e9a0ee1736` | 10-23 16:54:12—16 | `Scanning doc_graph rows...` → `No doc_graph rows found.` |
| `3f2af8facf5811f184dc27e9a0ee1736` | 10-24 11:08:54—55 | 同上；操作日志成功，完成时间 11:08:56 |

ES 的 `ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee` 索引按 KB 过滤：

- `local` 共 33 行：31 条普通切片、2 条 `doc_deleted` 删除标记；`entity/relation/graph` 均为 0。
- `db_t1` 共 850 行：164 条普通切片、345 条 doc scope 实体关系、339 条 dataset scope 实体关系、1 条 graph、1 条删除标记。

这同时排除了“Graph 已存在但前端没显示”和“收尾日志失败未 ACK”作为当前 `local` 空图的解释。先前收尾补丁有效，但不会替代知识编译；重复点击 Graph 不会补齐缺失的输入。

### 9.5 本地模型配置仍未切换完整

当前共享 `pipeline_t1` 的 Extractor、Compiler 均指向本地 Chat `4c01e862cebe11f184dc27e9a0ee1736`，但 **Parser 的 `setups.pdf.vlm.llm_id` 仍指向通义 `bbbb69b6ce8811f18a4cdf41f1d8e4ee`**。Spreadsheet、Markdown、Doc、Docx 等也保留通义 VLM 配置。租户默认 Chat、Vision 及库的 `parser_config.llm_id` 仍为通义；本地 Chat 在注册表中类型为 1（Chat），不能据名称将其当作已验证的视觉模型。

因此只给已有文档补绑流程仍可能再次触发欠费视觉调用。`rag/flow/parser/utils.py::enhance_media_sections_with_vision` 在指定 VLM 解析失败时会回退租户默认视觉模型；**清空节点 VLM 不等于禁用视觉增强**。`flatten_media_to_text` 会改变媒体处理和信息保留方式，本轮没有将其作为未经评估的关错开关。

### 9.6 恢复顺序与验收条件（本轮未执行数据重建）

1. 为 `local` 明确完整模型配置：Embedding 保留已验证本地模型；Extractor/Compiler 使用本地 Chat；图片理解应选择实际支持图片输入、已验证可用的本地 VLM。若不需要图片理解，应明确接受的信息损失并单独设计禁用方式，不把纯文本 Chat 填入 VLM。
2. 两库目前引用同一个流程 ID，修改它会影响之后两库的运行。需要保留 `db_t1` 配置时，应为本地流程保存独立副本，再核对 Compiler 模板组 `22f6f8c4ce8f11f18a4cdf41f1d8e4ee` 中包含目标图谱模板。
3. 通过文档解析配置或版本实际支持的文档更新 API，将 **现有文档**绑定到选定流程。单改知识库默认值后直接重跑仍会读取文档旧值。文档接口的 `reset_document_for_reparse` 会删除该文档旧切片/图片，先保留原文件及备份，再执行重建；不要用 SQL 强改状态绕过清理。
4. 先用 23 页用户手册验收：任务类型为 `dataflow`，节点依次执行，Compiler 有非零输出，Indexer 使用本地 Embedding 成功写入，文档 `run=3/progress=1`，日志无欠费调用。再检查 doc scope 的实体/关系和模板 ID。
5. 随后运行 Artifacts Graph，应出现 `Built N/N dataset graph(s)`，且 dataset scope 实体关系非零、界面有节点和边。还要核对来源文档、操作日志、完成时间和队列；不能只验收 100%。
6. 抽样检索和图谱内容质量通过后，再扩大文件范围。两种模型的向量虽均为 1024 维，仍不能混写向量空间；旧库迁移需统一重建。

### 9.7 可复现的只读检查

先按第 2 节运行现有检查工具，使用本次文档 ID：

```bash
cd /home/cdky/workspace/github/ragflow/docker/split
bash ops.sh app exec -T ragflow python - \
  --doc-id 01c62d1ccebe11f184dc27e9a0ee1736 < inspect_task.py
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

本地私有证据位于 `docker/split/evidence/`：`current-20261024.json`（两库快照）、`local-task-20261024.json`（队列与心跳）、`models-20261024.json`（节点及本地接口检查）、`worker-summary-20261024.json`（执行日志摘要）、`hashes-91.json/92.json/container.json`、`container-tests-20261024.txt`。不包含 API Key；文件名、模型配置和运行日志仍应按内部材料管理，目录已被 Git 和 Docker 构建上下文忽略。

## 10. 现有改动相对官方 v0.27.2 的审查

### 10.1 基线与逐文件结论

本地、91、92 的 HEAD 都是官方 tag `v0.27.2` 对应的 `a024bea0cd93f39e6652a42bf84dd20c55bc560b`。以该提交的 `git show HEAD:<path>` 为原实现，不与不断变化的 main 混比。检查了所有 `api/deepdoc/rag/test` 工作区改动及其调用链。

| 文件 / 修改 | 解决的问题 | 结论与边界 |
| --- | --- | --- |
| `api/db/__init__.py` 删除重复类型集合 | 旧集合遗漏 StructureGraph 等类型，与 `common.constants` 不一致 | 有效；仓库消费者已统一，无残留导入旧集合 |
| `api/db/services/pipeline_operation_log_service.py` 改用统一集合 | Graph 完成时写操作日志抛 `Invalid task type` | 有效；当前 local 两次操作日志均正常 |
| 同文件按 KB 实际 task_id 选择完成字段 | `graph` 入口与显式 `structure_graph` 入口共用任务类型但存入不同字段 | 有效；新任务引用已存在时可跳过旧任务；并发窗口尚未完全封闭，见 10.3 |
| `rag/svr/task_executor.py` 隔离收尾日志异常 | 日志异常跳过 ACK，留下已完成但 pending 的消息 | 有效；成功/失败均确认已处理消息，执行器 CancelledError 不确认未完成任务；不保证日志失败时日志自动补写 |
| `rag/flow/pipeline.py` 以实例状态累计节点进度 | Redis 轨迹过期丢失已完成节点；无文本回调不更新；重复节点重复累计 | 有效；缓存不再是进度的唯一来源；不是 OCR 断点恢复或剩余时间估计 |
| 同文件删除注释代码 | 过时的同步/异步调用备选分支 | 合理清理，无运行行为变化 |
| `deepdoc/parser/pdf_parser.py` 增加 OCR、逐表及批内进度回调 | 长 PDF 的批内静默，无法观察正在处理的页段和表格 | 有效；保留 50 页窗口、旋转判断和坐标算法；不构成已验证的算法加速 |
| `test/unit_test/rag/flow/test_pipeline_progress.py`（7 项） | 缓存过期/不可用、纯数字、乱序、失败、取消、完成 | 有针对性；使用 stub，不是全流程/模型质量验收 |
| `test/unit_test/api/db/services/test_graph_operation_completion.py`（9 项） | 新类型、入口字段映射、读取时已有更新任务 | 有针对性；没有测试读写之间并发替换 task_id |
| `test/unit_test/rag/svr/test_task_executor_finalization.py`（4 项） | 日志失败 ACK、执行失败、执行器取消 | 有针对性；AST 载入真实 handler，依赖为 mock，不覆盖 Redis 网络失败 |
| `test/unit_test/deepdoc/parser/test_pdf_parser_table_coordinates.py`（13 项） | 既有旋转坐标、增加表格回调及三批页段进度 | 有效；新增回调断言不应被描述为本轮修复了旧坐标算法 |

附带核对：`.dockerignore` 排除分离部署凭据/日志/备份/证据，目的合理；`build_patch.sh` 的五文件清单与 Dockerfile COPY 范围一致。`CLAUDE.md` 在仓库指向 `AGENTS.md`，Windows 当前显示为不可直接读取的 reparse point，本轮使用 `AGENTS.md`，没有改写此链接。Go testdata 链接也未纳入本轮 Python 修复或回退。

### 10.2 测试及部署一致性证据

- 统一 CRLF/LF 后，5 个 Python 运行文件与 4 个测试文件在本地、91、92 的 SHA-256 全部相同；当前应用容器的 5 个运行文件也相同。生产镜像不包含这 4 个测试文件，不把“镜像中没测试”误报为源码不一致。
- 本地 Python 3.14：第 9.1 节部署手册中的 4 文件命令，**33 passed**。
- Python 3.13 补丁镜像：生产容器未安装 pytest；使用相同镜像启动 `--rm --network none` 的隔离容器，挂载此前准备的 `/tmp/ragflow-patch-tests/pytest-runtime` 只读测试依赖，在临时目录复制源码及测试，**33 passed**。3 条 `p1` 未注册警告来自临时目录未使用仓库 pytest 配置，不是测试失败；未向生产容器安装包。
- 官方基线实验在本地私有 `evidence/baseline/` 副本进行，未覆盖工作区或服务器源码。相同 33 项检查为 **21 failed / 12 passed**；测试假模块额外提供了从原 `api/db/__init__.py` 提取的旧类型集合，以避免把导入桩缺项误判成业务失败。
- 基线失败拆分：Pipeline 7 项、Graph 9 项、日志失败 ACK 1 项、PDF 4 项。PDF 的 3 项是原方法不接受新增 callback 参数，1 项是原批内没有回调；因此该数字不能解释为“发现 21 个独立 bug”。
- 再仅为基线副本统一类型来源，Graph 检查变为 **3 failed / 6 passed**：`graphrag_task_finish_at`、`mindmap_task_finish_at` 字段写错，以及旧任务仍更新字段。说明完成字段补丁并非冗余。

上述验证足以支持保留现有补丁；不代替真实 PDF 内容质量、数据库并发或完整本地 Compiler → Graph 验收。

### 10.3 仍需处理的代码边界

**P2：完成时间写入仍有并发竞态。** `PipelineOperationLogService.create` 在读取 KB 的任务引用后，调用 `KnowledgebaseService.update_by_id`；后者 SQL 仅以 KB ID 为条件。如果新 Graph 在两步之间更新 `graphrag_task_id`，旧任务仍可能将其完成时间写入新任务对应字段。当前补丁防住的是“读取时已经换成新任务”，不是原子防护。建议在所属数据访问层使用 `WHERE kb_id=... AND <task_id_field>=finished_task_id` 的条件更新，并补充交错执行测试。本轮没有现场并发触发证据；不要将它说成此次空图的根因。

**官方 Graph 合并器的成功状态不保证产物成功。** 除无输入按 100% 结束外，`run_structure_merge` 的 Embedding 绑定异常分支也写 100%；逐模板构建捕获异常后最后仍写 `Built rebuilt/total` 的 100%。`_collect_structure_pairs` 的查询异常会直接退出扫描，可能被解释成空输入。这些路径都已存在于基线，本地补丁未修改它们。后续应区分空输入、真实异常和成功，并让执行失败进入失败终态。本次已通过独立 ES 查询确认 `local` 实际无编译记录，没有证据证明它触发了这些异常分支。

**视觉增强失败与最终成功的语义仍需明确。** 当前普通解析允许图片理解失败后完成文本入库；对训练数据制作或评测，必须另验媒体描述覆盖率，不能仅筛选 `run=3`。Pipeline 补丁的失败状态保留只作用于该实例回调；底层 TaskService 仍允许最终 1 覆盖 -1，不应将单元测试结论扩展成全系统不可恢复终态保证。

本轮结论是保留有证据支持的改动，记录上述未覆盖边界。没有以修复配置问题为由增加 vLLM 特判、跳过 Compiler、强制生成成功状态或移除有效测试；也没有改动现有模型配置、重建知识库或发布新的运行镜像。
