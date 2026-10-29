# 历史知识库数据清理手册

适用环境：91 应用 + 92 存储的分离部署。2026-10-26 已完成只读现场核对；本文中的停机、备份、删除和重启命令均未执行。本次不记录 `update.md`。

目标：清除旧知识库的原文、图片、分块/向量/图谱、任务和运行历史，保留账号、租户、模型配置、解析流程定义及系统管理配置。不是把整个 RAGFlow 恢复出厂设置。

## 1. 当前环境与清理范围

| 项目 | 实际位置 |
| --- | --- |
| 新应用 | `192.168.88.91:8088`；容器 `ragflow-app-ragflow-1` |
| 应用镜像 | `ragflow-local:v0.27.2-progress-20261023` |
| MySQL | `192.168.88.92:3306`，库 `rag_flow` |
| Elasticsearch | `192.168.88.92:9200` |
| MinIO API / Console | `192.168.88.92:9000` / `:9001` |
| Redis | `192.168.88.92:6379`，逻辑库 **DB 1** |
| 两台服务器项目目录 | `/home/cdky/workspace/github/ragflow` |
| 运维目录 | 项目下 `docker` |

91 上同时运行旧实例 `ragflow-server`，网页端口 `8890`，且有旧 MySQL、MinIO、Redis、ES。**本文不操作旧实例，不使用 91 的 9000/9001/9200 等旧存储端口。**

当前只读盘点结果如下，执行清理前需要停机后复核，不能把今天的数量当作以后始终成立的条件。

| 数据位置 | 当前结果 | 本次处理 |
| --- | --- | --- |
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

## 2. 为什么页面删除后仍有数据

现场容器中的知识库删除、文档删除、ES 索引删除三个实现文件，与本地对应文件的 SHA-256 一致，可以用本地代码解释当前行为：

- `api/apps/services/dataset_api_service.py::_delete_datasets_sync` 主要删除知识库、文档、文件关联等，并调用各存储清理逻辑；这些操作不是跨 MySQL/ES/MinIO/Redis 的统一事务。
- `api/db/services/document_service.py::remove_document` 按文档清理任务、分块和部分图片，但部分清理失败只记录日志。该路径没有完整清空 KB 对象桶及共享 `imagetemps`。
- `common/doc_store/es_conn_base.py::delete_idx` 在传入 KB ID 时直接返回，因为同租户的多个 KB 共用一个 ES 索引。知识库级图谱和删除标记不能仅靠文档 ID 删除来全部覆盖。
- `rag/utils/base64_image.py::image2id` 默认桶为 `imagetemps`；解析流程存在使用该默认桶的调用。它是共享存储位置，不能仅凭名称认定所有对象都可以删。

因此，要同时处理关系数据、检索数据、对象和任务状态。**空桶、空索引、基础目录存在本身不影响从头构建。**

## 3. 暂停写入并完成备份

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

## 4. 停机后复核并清理 MySQL

在 92 打开新实例的 MySQL 交互终端：

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh into storage mysql
MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -u ragflow -D rag_flow
exit
```

先执行只读 SQL，复核与第 1 节一致：

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

本次仅执行下面的定向删除，不删 `file`、账号、模型、流程表：

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

后续如果盘点发现文件版本/知识库编译历史，还需按 KB/文件夹归属处理 `file_commit_item`、`file_commit` 及其对象内容；如果发现连接器，则解绑 `connector2kb` 并清理对应同步任务。当前这些表没有相关数据，无需做全表清空。

## 5. 清理 Elasticsearch

当前所有 KB 都已删除，两个业务索引中的内容均不需要保留，可以删除下面两个**精确索引名**。不要删除 `.kibana*`、`.security*`、`.internal*` 等系统索引，也不要使用全索引删除。

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
for index in \
    ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee \
    ragflow_doc_meta_514a9b36ce8511f18a4cdf41f1d8e4ee
  do
    curl -fsS -u "elastic:$ELASTIC_PASSWORD" -X DELETE "http://localhost:9200/$index"
  done
exit
```

每个请求应返回 `acknowledged: true`。如果以后仅删除某个 KB，而租户仍有其他 KB，就必须按 `kb_id` 对业务索引进行定向删除，不能删整个租户索引。编译历史还可能使用 KB ID 命名的独立索引，需结合实际清单识别，不能只检查一个预设索引。

## 6. 清理 MinIO

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

确认只涉及这三个桶，再执行删除对象及未完成分片上传：

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh into storage minio
for bucket in 5ef3b38ecea911f18a4cdf41f1d8e4ee f98bec50ce8f11f18a4cdf41f1d8e4ee imagetemps
  do
    mc rm --recursive --force --versions "kbcleanup/$bucket/"
    mc rm --incomplete --recursive --force "kbcleanup/$bucket/"
  done
  mc rb kbcleanup/5ef3b38ecea911f18a4cdf41f1d8e4ee
  mc rb kbcleanup/f98bec50ce8f11f18a4cdf41f1d8e4ee
  mc ls kbcleanup
  mc ls --recursive --versions kbcleanup/imagetemps
exit
```

这三个桶盘点时均未开启版本控制；命令仍覆盖对象版本及未完成上传，以免只清掉当前可见对象。不要绕过对象锁/保留策略；若删除报错，检查错误原因后再继续。

本次可以清空 `imagetemps`，前提是停用全部新实例解析/调试任务、放弃历史运行图片，并清理关联运行缓存。它是跨任务共享桶；如果以后要保留部分 KB 或流程调试记录，就不能照搬整桶清空。

保留 `imagetemps` 空桶和用户根目录空桶是正常结果。不要删除全部 UUID 桶：某些桶对应用户目录、工作区或其他有效文件。不要直接删除 Docker 卷里的 MinIO 内部文件。

## 7. 清理 Redis 的旧任务与运行缓存

只处理 **92 的 DB 1**。当前没有在途任务、会话或 Memory 数据，但存在 `id_generator:memory` 计数器，保留它。这里不使用 `FLUSHALL`，也不要求清空整个 DB。

在 92 先列出待删 key，核对均为本次实例的任务/调试状态：

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

上述模式根据本次单独部署、全部 KB 重建的范围选取；如果有别的应用共用 DB 1，须改用核准的精确 key 清单。`canvas:replica:*` 是运行/调试副本，删除后丢弃旧调试状态；保存在 MySQL 的解析流程定义和版本仍保留。

预览确认后执行：

```bash
cd /home/cdky/workspace/github/ragflow/docker
bash docker.sh into storage redis
export REDISCLI_AUTH="$REDIS_PASSWORD"
  for pattern in "doc:chunking_*" "canvas:replica:*" "*-cancel" "*-logs" "te.*.common" "task_executor_*" "TASKEXE"
  do
    redis-cli -n 1 --scan --pattern "$pattern" |
    while IFS= read -r key
    do
      [ -z "$key" ] || redis-cli -n 1 UNLINK "$key"
    done
  done
  redis-cli -n 1 --scan
exit
```

若仍有旧解析缓存，应核对其来源后追加精确 key，不能为了让 `DBSIZE=0` 而删计数器或其他系统状态。当前两个 Stream 没有 pending，9 条历史消息已经消费；这不代表历史流记录会自动消失。

## 8. 验收与恢复服务

先在停机状态验收：

- MySQL：`knowledgebase`、`document`、`file2document`、`task`、`pipeline_operation_log` 都为 0；连接器关联、同步日志及文件版本表无旧 KB 记录。
- ES：两个指定旧业务索引不存在；系统索引仍保留。
- MinIO：两个旧 KB 桶不存在；`imagetemps` 没有对象、旧版本和未完成上传；用户根目录空桶仍在。
- Redis：旧解析任务流、状态、调试副本已清除；允许保留计数器。
- 保留项：2 个账号/租户、4 个基础目录、2 个解析流程及 20 个流程版本；模型供应商/模型实例/分组配置和 API 凭据未改动。

然后在 92 检查存储健康，在 91 启动新应用：

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

新建一个小型测试 KB，上传一份小文档，验证解析、分块、检索和图片显示。新桶、新索引、新 `imagetemps` 对象都会按需出现。删除测试 KB 后按新 ID 再检查残留；当前删除代码没有修改，因此同类残留可能再次出现。

原有对话助手、搜索配置、Agent 或数据源若引用旧 KB ID，需改绑新 ID；同名重建 KB 不会复用旧 ID。当前会话表为空，但仍应检查保留的流程配置。应用日志和运维备份不影响新 KB 建库；如目标还包括敏感内容彻底销毁，应另行确定日志、快照、备份的保留范围，不能与本次活动数据清理混为一谈。

## 9. 出错时的处理与后续改进

任一删除步骤失败，保持新应用停止，保存错误及已完成步骤，先核查再继续。若要回滚，使用第 3 节同一时间点的备份成套恢复 MySQL、ES、MinIO、Redis；ES 优先使用已验证成功的 snapshot。不要只回滚 MySQL 后继续服务，否则索引和对象可能仍然缺失。恢复流程见 `docs/install.md` 第 6 节，目标仅限 `ragflow-storage` 的卷和服务。

长期应完善知识库删除逻辑：先停止/解绑生产任务，按 KB 范围清理所有派生索引数据和对象，再清理运行历史及关联；共享图片需要可追踪的归属和回收机制。本文没有修改代码，也没有设置 `imagetemps` 的自动过期规则，避免误删仍被有效结果引用的图片。

外部参考：[RAGFlow 官方仓库](https://github.com/infiniflow/ragflow)。用户提供的 [v0.27.2 HTTP API 文档地址](https://ragflow.io/docs/v0.27.2/http_api_reference) 本次访问返回 404，因此本文命令与行为判断以现场部署和已核对的本地源码为准。
