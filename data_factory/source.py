"""Read-only connection to the configured RAGFlow Python API."""

import hashlib
import io
import json
import os
import re
from collections import defaultdict

import requests
from PIL import Image


class FactoryError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", value):
        raise FactoryError("来源 ID 无效")
    return value


class Source:
    def __init__(self, authorization):
        if not authorization:
            raise FactoryError("请提供开发环境的 RAGFlow API Key", 401)
        self.authorization = authorization

    def get(self, path, **params):
        return self._request("GET", path, params=params)

    def retrieve(self, kb, docs, query, config):
        if config["retrieval"] == "lexical":
            chunks = []
            for doc in docs:
                found = self.get(f"/datasets/{kb}/documents/{doc}/chunks", keywords=query, page_size=config["candidate_count"], available="true")
                for hit in found["chunks"]:
                    # Keyword search may highlight text. Fetch the actual current body before comparing to the snapshot.
                    clean = self.get(f"/datasets/{kb}/documents/{doc}/chunks", id=hit["id"])
                    if clean["chunks"]:
                        chunks.append(dict(clean["chunks"][0], similarity=None))
            return {"chunks": chunks[: config["candidate_count"]]}
        return self._request(
            "POST",
            "/retrieval",
            json={
                "dataset_ids": [kb],
                "document_ids": docs,
                "question": query,
                "page_size": config["candidate_count"],
                "vector_similarity_weight": 1 if config["retrieval"] == "vector" else config["vector_weight"],
                "similarity_threshold": config["threshold"],
                "knn_top_k": config["knn_top_k"],
                "knn_num_candidates": config["knn_candidates"],
                "rerank_candidates_count": max(64, config["candidate_count"]),
                "rerank_id": "",
                "include_knowledge_compilation": False,
            },
        )

    def generate(self, prompt, model_id, tokens):
        return self._request("POST", "/data-factory-model/generate", json={"prompt": prompt, "model_id": model_id, "max_tokens": tokens})

    def rerank(self, query, texts, model_id):
        return self._request("POST", "/data-factory-model/rerank", json={"query": query, "texts": texts, "model_id": model_id})

    def original(self, kb, doc):
        url = os.environ["RAGFLOW_API"].rstrip("/") + f"/datasets/{kb}/documents/{doc}"
        with requests.get(url, headers={"Authorization": self.authorization}, stream=True, timeout=(4, 60), allow_redirects=False) as response:
            response.raise_for_status()
            data = bytearray()
            for block in response.iter_content(65536):
                data.extend(block)
                if len(data) > 32 * 1024 * 1024:
                    raise FactoryError("单个来源文件超过 32 MiB")
            return bytes(data), response.headers.get("Content-Type", "application/octet-stream").split(";")[0]

    def _request(self, method, path, **kwargs):
        base = os.environ["RAGFLOW_API"].rstrip("/")
        try:
            response = requests.request(method, base + path, headers={"Authorization": self.authorization}, allow_redirects=False, timeout=(4, 120), **kwargs)
            if response.status_code in (400, 401, 403, 404):
                raise FactoryError("RAGFlow 拒绝访问", 403)
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise FactoryError("无法读取 RAGFlow 接口", 502) from exc
        if body.get("code") != 0:
            raise FactoryError("来源不可访问，请检查身份与来源权限", 403)
        return body["data"]

    def authorize(self, sources):
        documents = defaultdict(set)
        for kb, doc in sources:
            documents[kb].add(doc)
        for kb, ids in documents.items():
            rows = self.get(f"/datasets/{kb}/documents", ids=sorted(ids), page_size=len(ids))["docs"]
            if {r["id"] for r in rows} != ids:
                raise FactoryError("部分来源文档已删除或不可访问", 403)

    def image(self, kb, chunk):
        key = kb + "-" + identifier(chunk["id"])
        if chunk["image_id"] != key:
            raise FactoryError("图片不是当前知识库切片的独立对象")
        url = os.environ["RAGFLOW_API"].rstrip("/") + "/documents/images/" + key
        with requests.get(url, headers={"Authorization": self.authorization}, stream=True, timeout=(4, 30), allow_redirects=False) as response:
            response.raise_for_status()
            stream = io.BytesIO()
            for part in response.iter_content(65536):
                stream.write(part)
                if stream.tell() > 8 * 1024 * 1024:
                    raise FactoryError("图片超过 8 MiB")
            stream.seek(0)
            with Image.open(stream) as image:
                if image.format not in ("PNG", "JPEG", "WEBP") or image.width * image.height > 12000000:
                    raise FactoryError("不支持的图片格式或分辨率")
                image.load()
                return stream.getvalue(), Image.MIME[image.format], image.size

    def capture(self, kb, doc, check):
        path = f"/datasets/{kb}/documents/{doc}/chunks"

        def read():
            rows = {}
            page = 1
            while True:
                check()
                data = self.get(path, page=page, page_size=100, available="true")
                meta = data["doc"]
                if meta["run"] != "DONE":
                    raise FactoryError(f"文档 {doc} 尚未完成解析")
                for chunk in data["chunks"]:
                    if chunk["document_id"] != doc or not chunk["available"]:
                        raise FactoryError("来源返回了范围外的切片")
                    rows[chunk["id"]] = {k: chunk.get(k) for k in ("id", "content", "questions", "important_keywords", "positions", "image_id", "doc_type_kwd")}
                if len(rows) > 20000:
                    raise FactoryError("单文档超过 20000 个切片，请缩小来源")
                if page * 100 >= data["total"] or not data["chunks"]:
                    break
                page += 1
            if len(rows) != data["total"]:
                raise FactoryError("分页数量不一致，请重试")
            return {"kb": kb, "doc": doc, "name": meta["name"], "parser": meta.get("parser_config", {}), "chunks": [rows[key] for key in sorted(rows)]}

        snapshot = read()
        if not snapshot["chunks"]:
            raise FactoryError(f"文档 {doc} 没有启用的切片")
        if snapshot != read():
            raise FactoryError(f"文档 {doc} 在读取期间变化，请重试")
        return snapshot
