# 通过 Kibana 查看 RAGFlow 的 ES 数据

2026-10-27 核查：Kibana 状态 available，Elasticsearch 8.11.3；目标 chunk、1024 维向量、Term vectors 和 Explain 请求均只读验证通过。本页不修改索引或知识库。

## 1. 登录和选择入口

- 地址：<http://192.168.88.92:5601>。
- 用户名：`elastic`；密码取 92 的 `/home/cdky/workspace/github/ragflow/docker/split/storage.env` 中 `ELASTIC_PASSWORD`，不是 Linux 登录密码。`kibana_system` 是服务内部连接账号，不用于人工登录。
- 精确查询使用 **Dev Tools → Console**。粘贴下面请求，把光标放在该请求内，点击运行按钮或按 Ctrl+Enter。这里的 GET/POST 查询均为读取，不会调用 Embedding/LLM。
- 表格浏览使用 **Discover**，配置见第 7 节。

本租户索引为 `ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee`。一个索引里有多个知识库，不能把租户索引当作 t4 独占数据库；通过 `kb_id` 区分。t4 的 KB ID 为 `3c845f96d1ac11f18715a9a4fa662e3a`。

## 2. 列索引、看字段定义

```http
GET _cat/indices/ragflow*?v

GET ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee/_mapping
```

重点字段：

| 字段 | 含义 |
| --- | --- |
| `content_with_weight` | 保存的正文；本部署 `index=false`，可显示，不能据此字段做全文匹配 |
| `content_ltks` / `content_sm_ltks` | 全文检索分词；ES analyzer 为 whitespace，接收 RAGFlow 已分词的文本 |
| `q_1024_vec` | 1024 维 dense_vector，`index=true`、cosine 相似度 |
| `doc_id` / `kb_id` | 所属文档/知识库，keyword 精确过滤 |
| `compile_kwd` | 编译产物标记，可用于排除普通 chunk 之外的行 |
| `source_chunk_ids` | 图谱记录引用的源 chunk ID |

## 3. 查看 t4 的普通 chunk

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

## 4. 查看 BM25 的词项和统计

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

在 `term_vectors.content_ltks.terms` 查看每个词：`term_freq` 是该文档词频，`doc_freq` 是包含该词的文档数，`ttf` 是总词频；`field_statistics` 返回字段统计。统计具有分片范围限制，不是只针对 t4 的精确库内统计。接口也可按需从字段内容计算词项，不等于导出 Lucene 底层倒排索引文件。[官方说明（8.11）](https://www.elastic.co/guide/en/elasticsearch/reference/8.11/docs-termvectors.html)

本次 t4 题注正文是 `图1. 迪丽热巴`，但分词字段是“您好 您 似乎 忘记 粘贴 需要 总结……”——这是摘要提示词没有绑定正文导致的结果，不是 Kibana 显示错误。

## 5. 看 BM25 查询得分和命中原因

以下使用现场分词中确实存在的 `您好`，便于观察完整评分解释；它是诊断示例，不是推荐的业务查询词。

```http
GET ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee/_explain/cbae5b080fb2ca3b
{
  "query": {
    "match": {"content_ltks": "您好"}
  }
}
```

返回 `matched` 和 `explanation`，向下展开可查看 BM25 的词频、逆文档频率及长度归一化等评分组成。本次 `matched=true`；评分随索引数据变化，不应把现场分数当作常量。[Explain 官方说明（8.11）](https://www.elastic.co/guide/en/elasticsearch/reference/8.11/search-explain.html)

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

## 6. 查看向量及图谱引用

只返回正文、标识与向量，减少无关字段：

```http
GET ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee/_doc/cbae5b080fb2ca3b?_source_includes=id,doc_id,kb_id,content_with_weight,q_1024_vec
```

展开 `_source.q_1024_vec` 可看到 1024 个浮点值。本次前四维为 `[-0.005249786376953125, 0.04124298095703125, -0.03345322608947754, -0.04250946044921875]`。向量不是可还原为文字的解释字段；语义相似度要使用同一 Embedding 模型、相同维数生成查询向量再检索。查看数值本身不需要再次调用模型。这里按 ES 8.11.3 的实际返回给出请求，无需添加新版本的 `exclude_vectors` 参数。

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

它只查直接引用：不会包含没有顶层 `source_chunk_ids` 的图谱汇总 JSON，也会漏掉只引用图片块但描述中出现旧名的实体。完整影响范围见 [t4 局部修正手册](data-storage-and-local-correction.md)。

## 7. 在 Discover 中表格浏览

1. 打开 **Discover → Create data view**。
2. 名称自定，Index pattern 填精确索引名 `ragflow_514a9b36ce8511f18a4cdf41f1d8e4ee`。
3. Timestamp field 选择 **I don't want to use the time filter**，避免默认时间范围将旧块或没有时间字段的图谱记录过滤掉。Data view 只建立 Kibana 查看配置，不重新构建 ES 索引。[官方说明（8.11）](https://www.elastic.co/guide/en/kibana/8.11/data-views.html)
4. KQL 输入：

```text
kb_id: "3c845f96d1ac11f18715a9a4fa662e3a" and not compile_kwd: *
```

5. 添加列：`id`、`doc_id`、`chunk_order_int`、`doc_type_kwd`、`content_with_weight`、`content_ltks`、`img_id`。查看图谱时去掉 `not compile_kwd: *`，增加 `knowledge_graph_kwd`、`name_kwd`、`source_chunk_ids`。
6. 点行左侧展开查看字段/JSON。向量长数组、精确 term statistics 和评分解释优先用 Console。

只需要查看时执行本页查询即可。若需改正文，使用 RAGFlow chunk 更新接口；在 Kibana 直接只改 `content_with_weight` 会留下旧分词和旧向量。
