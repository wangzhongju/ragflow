"""Durable checkpoints with fenced, budgeted task execution."""

import json
import logging
import mimetypes
from concurrent.futures import ThreadPoolExecutor

from . import assets
from .embedding import prepare, preserve_partitions
from .source import FactoryError, canonical, digest
from .store import database

worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="data-factory")


def capture_source(ds, owner, kb, doc, source, check):
    with database() as db:
        row = db.execute("SELECT body FROM capture WHERE dataset=? AND doc=?", (ds, doc)).fetchone()
    if row:
        return json.loads(row[0])
    document = source.capture(kb, doc, check)
    data, mime = source.original(kb, doc)
    mime = mimetypes.guess_type(document["name"])[0] or mime
    with database(True) as db:
        check(db)
        sha = assets.register(db, owner, data, mime, document["name"])
        assets.relate(db, ds, owner, sha, doc, "original")
    document["original_asset"] = sha
    document["media_type"] = mime.split("/")[0]
    original_sha = sha
    pages = {}
    for chunk in document["chunks"]:
        check()
        if chunk["doc_type_kwd"] == "image" and chunk["image_id"] == kb + "-" + chunk["id"]:
            image, image_mime, size = source.image(kb, chunk)
            with database(True) as db:
                check(db)
                sha = assets.register(db, owner, image, image_mime, chunk["id"], {"width": size[0], "height": size[1]})
                assets.relate(db, ds, owner, sha, doc, "image", original_sha, {"chunk_id": chunk["id"], "positions": chunk.get("positions")})
            chunk["asset_sha256"] = sha
        elif mime == "application/pdf" and chunk.get("positions"):
            # Render from the authorized original when a parser uses a shared temporary image bucket.
            page = int(chunk["positions"][0][0])
            if page not in pages and len(pages) < 10:
                import io

                import pypdfium2

                pdf = pypdfium2.PdfDocument(data)
                try:
                    if not 1 <= page <= len(pdf):
                        raise FactoryError("PDF 页码超出原件范围")
                    p = pdf[page - 1]
                    bitmap = p.render(scale=1.5)
                    image = bitmap.to_pil()
                    stream = io.BytesIO()
                    image.save(stream, format="PNG")
                    with database(True) as db:
                        check(db)
                        page_sha = assets.register(db, owner, stream.getvalue(), "image/png", f"page-{page}.png", {"width": image.width, "height": image.height})
                        assets.relate(db, ds, owner, page_sha, doc, "page", original_sha, {"page": page})
                    pages[page] = page_sha
                    bitmap.close()
                    p.close()
                finally:
                    pdf.close()
            if chunk["doc_type_kwd"] == "image":
                chunk["asset_sha256"] = pages.get(page)
    for chunk in document["chunks"]:
        if not chunk.get("content"):
            continue
        with database(True) as db:
            check(db)
            text_sha = assets.register(db, owner, chunk["content"].encode(), "text/plain", chunk["id"] + ".txt")
            page = int(chunk["positions"][0][0]) if chunk.get("positions") else None
            assets.relate(db, ds, owner, text_sha, doc, "extracted_text", pages.get(page, original_sha), {"chunk_id": chunk["id"], "positions": chunk.get("positions") or []})
            chunk["text_asset_id"] = text_sha
    document["pages"] = pages
    with database(True) as db:
        check(db)
        # Idempotent resume may already have registered assets, so the capture is the commit point.
        db.execute("INSERT OR IGNORE INTO capture(dataset,doc,body) VALUES(?,?,?)", (ds, doc, canonical(document)))
    return document


def produce(ds, attempt, source):
    from .generators import GENERATORS, candidates, queries

    def check(db=None):
        if db is None:
            with database() as reader:
                return check(reader)
        row = db.execute("SELECT state,attempt FROM dataset WHERE id=?", (ds,)).fetchone()
        if not row or row["state"] != "running" or row["attempt"] != attempt:
            raise FactoryError("任务已取消或已重新提交")

    try:
        with database(True) as db:
            if not db.execute("UPDATE dataset SET state='running' WHERE id=? AND attempt=? AND state='queued'", (ds, attempt)).rowcount:
                return
            row = dict(db.execute("SELECT * FROM dataset WHERE id=?", (ds,)).fetchone())
        config = json.loads(row["config"])
        sources = json.loads(row["sources"])
        source.authorize(sources)
        documents = []
        for kb, doc in sources:
            documents.append(capture_source(ds, row["owner"], kb, doc, source, check))
            if len(canonical(documents).encode()) > 16 * 1024 * 1024:
                raise FactoryError("来源快照超过 16 MiB，请拆分任务")
        evidence = prepare(documents, config, check)
        with database(True) as db:
            check(db)
            preserve_partitions(db, row["owner"], evidence)
        records = queries(documents, evidence, ds, config, source, check)
        if not records:
            raise FactoryError("没有可用问题，请选择模板或 LLM 生成方式，或补充来源 questions")
        drafts = []
        snapshot = digest(canonical(documents))
        for index, record in enumerate(records, 1):
            check()
            record["positives"] = list(dict.fromkeys(record["positives"]))[: config["positive_count"]]
            record = candidates(record, evidence, ds, config, source, check)
            payload = GENERATORS[row["task"]].payload(record, ds=ds, config=config, source=source, check=check, evidence=evidence)
            first = evidence[record["positives"][0]]
            from .schema import evidence_refs

            sample = {
                "schema_version": 2,
                "sample_id": str(index),
                "revision": 1,
                "task": row["task"],
                "snapshot_id": snapshot,
                "group_id": first["group_id"],
                "split": first["split"],
                "evidence_ids": [],
                "provenance": {
                    "job_id": ds,
                    "query_origin": record["origin"],
                    "model_id": config["model_id"],
                    "config_sha256": digest(row["config"]),
                    "warnings": record.get("warnings", []),
                    "candidate_snapshot": record["candidates"],
                    "uncertain_candidates": record.get("uncertain_candidates", []),
                },
                "payload": payload,
            }
            sample["evidence_ids"] = evidence_refs(sample)
            drafts.append(sample)
        source.authorize(sources)
        with database(True) as db:
            check(db)
            db.executemany("INSERT INTO evidence VALUES(?,?,?)", ((ds, k, canonical(v)) for k, v in evidence.items()))
            db.executemany("INSERT INTO revision(dataset,id,rev,body,status,actor,reason) VALUES(?,?,1,?,'draft','worker','')", ((ds, i, canonical(s)) for i, s in enumerate(drafts, 1)))
            db.execute("UPDATE dataset SET state='ready',snapshot=? WHERE id=?", (snapshot, ds))
    except Exception as exc:
        if not isinstance(exc, FactoryError):
            logging.getLogger(__name__).exception("Preparation failed for %s", ds)
        message = str(exc) if isinstance(exc, FactoryError) else "任务失败，请检查制作服务日志"
        with database(True) as db:
            db.execute("UPDATE dataset SET state='failed',error=? WHERE id=? AND attempt=? AND state='running'", (message, ds, attempt))
