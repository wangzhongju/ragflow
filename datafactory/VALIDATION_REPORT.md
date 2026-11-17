# DataFactory 91 开发部署验收记录

日期：2026-11-16。范围：当前已实现功能的真实账号、指定知识库、小预算模型及部署验证。完整操作说明见 [使用手册](USER_GUIDE.md)；修复过程见 [issue.md](../files/issue.md#datafactory-real-20261116)。

## 结论

当前已实现的文本检索数据制作链路通过真实环境验证：登录 → 知识库读取 → 快照 → 配方 → 预览/正式运行 → 审核 → 发布 → 四种文本格式下载。多模态语料的文本和图片冻结、图片查看及资产校验通过。

**本记录不代表 M0/M1/M2 全部完成，也不代表图片模型输入、图片查询、音视频训练制作或容量验收通过。** 一次本地模型调用超时留下 1 条未知计费记录，仍需核实，未擅自填零或重发。

## 环境与数据边界

- 页面：<http://192.168.88.91:9391/factory/>。
- 项目：`真实知识库验收_20261116`，ID `prj_01M7HDX1HRPWCV111V4KTXYZBN`。
- 来源：用户指定知识库 `数据制作多模态验收_20261104`，8 文档、70 切片。
- DataFactory 的数据库 `datafactory_dev_91`、Redis 前缀和 MinIO 桶独立；迁移版本 `0008_release_manifest`。
- 本次未连接 92 主机，未修改源知识库内容；源文档 ID、哈希、切片/Token 数、解析状态、进度、更新时间和解析器在测试前后逐项相同。
- 开发 Gateway 以独立 Compose 服务加载同一份 RAGFlow 代码，只在 Docker 网络监听 9392，不公开主机端口。未重启主 RAGFlow 容器，未运行其数据库初始化/迁移。

## 验证结果

| 项目 | 实际结果 |
| --- | --- |
| 浏览器真实登录 | `/api/v1/auth/login`、平台 `/me` 均 200；复用真实 RAGFlow 身份 |
| 知识库与模型目录 | 指定知识库及已配置模型可读；Embedding ID 正确解析为 1024 维模型 |
| 完整快照 | `snap_01M7HEN0TEKXYNZ930CBYCEWDP`：70 切片、8 文档、68 mixed + 2 text |
| 冻结资产 | 44 个唯一图片资产，共 8,353,666 字节；全部 SHA-256 通过 |
| 资产 HTTP 行为 | Range 206、条件请求 304、匿名请求 401；快照过期检查 ready、无漂移 |
| 真实预览 | `run_01M7HF0A1ZTKVBVYNB7M17FJMJ`：4 次模型调用，完成并产出 1 个预览样本 |
| 正式正常路径 | `run_01M7HF7944FTM1MTDCWHF450ND`：4 次模型调用，完成并产出 1 个正式样本 |
| 审核 | 已根据来源文本核对查询与正负例，实际页面点击通过 |
| 发布 | `rel_01M7HFJGB5GTQFBFQR5R843SNX`：5 项门禁全部通过、released |
| 下载 | 实际浏览器完成四种格式预览与下载，无 JS 异常；包内哈希和重复下载字节一致 |
| 异常保护 | `run_01M7HF1Z2D2ATR7THPXTSAGAZX` 遇到模型超时后 paused，未知调用保留预留，恢复请求返回 409 / billed_unknown |
| 自动化回归 | 后端 unit 156 passed；Gateway 契约 19 passed（本地及 91 Python 3.13）；91 真实 MySQL/Redis/MinIO integration 3 passed；前端 12 passed，类型/lint/构建通过 |

首次构建失败的快照保留为诊断记录。首次模型预览 `run_01M7HER7Q8SHS4YGC2Y0S3M4SW` 因召回结果读取缺陷而无负例，过滤后 0 样本；没有伪造样本或绕过质量门禁。修复后新建预览成功。

## 正式样本说明

正式运行从 `flower.mp4` 已有的文字描述生成查询，另一条音频转写/解释文本作候选干扰项；它验证的是**文本检索制作**，没有把视频字节送入模型。快照为 `snap_01M7HF771K3QE8XS1HWMH0JPZ9`，数据集为 `ds_01M7HF7EW187T3S8G5V6A7VEYG`。

查询询问花苞周围肉质绿叶边缘的颜色，来源描述明确给出 purple-magenta。实际模型 judge=10；教师正例分约 0.8301、负例分约 0.0060，1 正例、1 负例、无假负例疑点。使用模型：`qwen3.7-flash-2026-07-15`、知识库自身 `qwen3.7-text-embedding-flash`、`gte-rerank-v2`，都经 Gateway 调用。

验收配方将 split 配为全部 test，用于验证 BEIR 的 queries/qrels 非空；这不是正式训练集的划分建议。仓库 [示例配方](examples/retrieval-text.json) 仍采用 0.8/0.1/0.1，正式制作应扩大样本量并独立审核源内容质量。

## 交付包校验

| 格式 | 包内文件数 | ZIP 字节数 | ZIP SHA-256 |
| --- | ---: | ---: | --- |
| canonical | 6 | 6419 | `9b6e013517abf2b73a874d378a400ca854d1ec7546cb75cf87fbed213d3c3eb0` |
| beir | 8 | 7690 | `d1cc0889c4184f489a40cf91c10c6ffca5237046642d6bcac8fad0c67bc72dbe` |
| sentence_transformers | 6 | 7060 | `e84b2ed9a7907bba548cd45e66ecba3cdd3fd1da08b2cccef26af51991a93961` |
| flagembedding | 6 | 7099 | `0df6fa7926eb9eb582139c6033ecfd72eb1bcc036f4cef30df042e409301c3e1` |

四包均逐项核对 `manifest.files` 的大小/哈希及 `SHA256SUMS`。BEIR 含 2 条语料、1 条 test 查询和对应 qrel。以上是纯文本子集包，因此不含图片文件；完整快照的 44 个图片资产已另行下载校验。可登录项目的发布页重新下载这些不可变包。

## 仍需跟进的账目

未知调用：`inv_01M7HF25S32DQ9HK6SETZ8C182`，本地 `qwen3-text-generation` 的 judge 调用。所属运行仍暂停，5 次调用、已确认 63 Token、保留 6855 Token 上界；其中部分预留也来自成功但未返回 usage 的 chat，不能把全部预留当作未知调用的实际费用。未核账、未自动重试。

owner 应使用该运行的调用时间、列、模型和行键查上游记录，仅在实际用量可核实后执行核账。不要用“测试超时”推断计费为零。本次另外使用不同种子和已配置的其他生成模型验证正常链路，没有恢复或重发这条未知调用。

## 本轮修复

1. 登录入口收敛到当前 `/api/v1/auth/login`，同步开发代理与指导文件。
2. 模型列表和调用鉴权按 Provider → Instance → Model 关系读取；排除停用实例/模型，不读取不存在的 TenantModel 字段。
3. 知识库模型引用解析为可调用 ID，切片扫描固定携带 doc_id/kb_id。
4. 图片读取以可访问知识库内的实际切片引用授权，支持真实 `imagetemps` 存储，同时保持跨用户拒绝。
5. 检索得分读取接受 Elasticsearch 客户端响应对象；Infinity 路径按列读取，避免 `_score` 元组字段重命名问题。
6. 空消息超时异常记录异常类型，后续不再只显示空的 Invocation 错误。

验收截图和操作入口见 [使用手册](USER_GUIDE.md)。未完成项继续以 [实施状态](design/IMPLEMENTATION_STATUS.md) 为准。
