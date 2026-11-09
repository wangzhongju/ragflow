# 外部 Agent 文件解析接口

适用于本工程 Python API 服务，新增代码发布后可用。此能力复用 `FileService.parse`，不创建知识库、文档记录、向量或对象存储文件。HTTP API 是调用入口，`sdk/skills/ragflow-parse-file/SKILL.md` 可复制到外部 Agent 的技能目录。当前未新增 MCP 工具，也未修改 Go 服务。

## 接口契约

两个接口均使用已有用户 API Key：`Authorization: Bearer <API Key>`，不是登录密码或 Beta token。

- `GET /api/v1/files/parse`：返回 `data.extensions`、`max_file_bytes`、`layout_modes`、`format`。
- `POST /api/v1/files/parse`：`multipart/form-data`，恰好一个 `file`；可选 `layout_recognize`，值为 `Plain Text`（默认）或 `DeepDOC`。其他字段、多个文件、空文件、未知扩展名拒绝。

单文件最大 20 MiB；multipart 整体最大 20 MiB + 64 KiB，部署的全局请求或代理限制更小时以更小值为准。支持 pdf/doc/docx/txt/md/markdown/html/htm/csv/xls/xlsx/json/jsonl/epub；扩展名支持不等于任意内容均可解析。Office、PDF、OCR 仍依赖服务端现有解析组件。普通文本模式不保证读取扫描 PDF，扫描件需 DeepDOC。响应为文本，不承诺版面坐标、图片或无损还原。

成功示例：

```json
{"code":0,"data":{"filename":"example.txt","size":5,"format":"text","content":"\n -----------------\nFile: example.txt\nContent as following: \nhello","layout_recognize":"Plain Text"}}
```

文本保留现有解析器生成的文件标题、分块拼接和表格标记。客户端应同时检查 HTTP 状态和 `code`；文本/HTML 为不可信文档内容，不能直接作为指令或未经清洗插入页面。

错误：400 输入错误；413 文件/请求过大；415 请求格式错误；422 解析失败（详细异常仅在服务日志）。认证失败沿用系统现有认证返回约定。同步调用通过现有有界长任务线程池执行；没有作业查询/取消接口，客户端超时不意味着底层解析终止，也没有结果持久化或自动重试。适合小文件即时解析，批量长任务仍应使用知识库异步入库流程。

## 开发环境调用

发布前先运行下述本地测试，再按现有开发发布流程同步到 **91** 并重启 Python 应用；此变更本身没有执行部署。92 为生产环境，不同步、不重启。91 与 92 存储共享，验证时不创建知识库或更新模型配置。

```bash
export RAGFLOW_BASE_URL=http://192.168.88.91:9380
# RAGFLOW_API_KEY 由调用环境安全注入，不把密钥写入脚本或文档
curl --fail-with-body -H "Authorization: Bearer ${RAGFLOW_API_KEY}" \
  "${RAGFLOW_BASE_URL}/api/v1/files/parse"
printf 'hello agent\n' > /tmp/ragflow-parse-example.txt
curl --fail-with-body --max-time 300 \
  -H "Authorization: Bearer ${RAGFLOW_API_KEY}" \
  -F 'file=@/tmp/ragflow-parse-example.txt' \
  "${RAGFLOW_BASE_URL}/api/v1/files/parse" \
  -F "layout_recognize=DeepDOC"  # 指定解析方式，默认Plain Text，可选DeepDOC
```

预期 `code=0` 且 `data.content` 包含 `hello agent`。随后用带文本层 PDF、扫描 PDF（DeepDOC）、DOCX、XLSX 各一份做真实解析验收，检查中文、表格和空结果。GET 404 表示代码未发布、未重启或代理路径错误，不能通过更换 API Key 修复。

## 本地验证

```bash
python -m pytest test/unit_test/api/apps/restful_apis/test_file_parse_api.py -q
python -m ruff check api/apps/restful_apis/file_parse_api.py api/apps/services/file_parse_service.py test/unit_test/api/apps/restful_apis/test_file_parse_api.py
```

测试使用真实 Quart multipart 请求，替换认证加载与原生解析依赖，验证接口契约及租户传递；不替代真实 API Key、数据库或 OCR 集成验收。请求体限制沿用 [Quart 请求处理机制](https://quart.palletsprojects.com/en/stable/discussion/dos_mitigations/)。
