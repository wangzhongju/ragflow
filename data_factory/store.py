import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .source import FactoryError, canonical, digest


@contextmanager
def database(write=False):
    db = sqlite3.connect(Path(os.environ["FACTORY_DB"]), timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield db
        db.commit()
    finally:
        db.close()


def initialize():
    from .assets import write_object
    from .schema import settings

    with database(True) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS dataset(id TEXT PRIMARY KEY,owner TEXT NOT NULL,name TEXT NOT NULL,sources TEXT NOT NULL,
            state TEXT NOT NULL,attempt INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',snapshot TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS dataset_owner ON dataset(owner);
        CREATE TABLE IF NOT EXISTS member(dataset TEXT REFERENCES dataset,user TEXT,role TEXT NOT NULL,PRIMARY KEY(dataset,user));
        CREATE TABLE IF NOT EXISTS capture(dataset TEXT REFERENCES dataset,doc TEXT,body TEXT NOT NULL,captured TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(dataset,doc));
        CREATE TABLE IF NOT EXISTS evidence(dataset TEXT REFERENCES dataset,id TEXT,body TEXT NOT NULL,PRIMARY KEY(dataset,id));
        CREATE TABLE IF NOT EXISTS revision(dataset TEXT REFERENCES dataset,id INTEGER,rev INTEGER,body TEXT NOT NULL,status TEXT NOT NULL,actor TEXT NOT NULL,reason TEXT NOT NULL,
            created TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(dataset,id,rev));
        CREATE TABLE IF NOT EXISTS version(dataset TEXT REFERENCES dataset,id TEXT,members TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(dataset,id));
        CREATE TABLE IF NOT EXISTS audit(dataset TEXT REFERENCES dataset,actor TEXT,version TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS asset(owner TEXT,sha TEXT,mime TEXT NOT NULL,object_key TEXT NOT NULL,size INTEGER NOT NULL,name TEXT NOT NULL,metadata TEXT NOT NULL,PRIMARY KEY(owner,sha));
        CREATE TABLE IF NOT EXISTS asset_ref(dataset TEXT REFERENCES dataset,owner TEXT,sha TEXT,doc TEXT,role TEXT,parent TEXT,locator TEXT,PRIMARY KEY(dataset,sha,doc,role,parent));
        CREATE TABLE IF NOT EXISTS partition(owner TEXT,fingerprint TEXT,family TEXT,split TEXT,PRIMARY KEY(owner,fingerprint));
        CREATE TABLE IF NOT EXISTS invocation(dataset TEXT REFERENCES dataset,id TEXT,kind TEXT,reserved INTEGER,state TEXT,result TEXT,model TEXT,metadata TEXT,PRIMARY KEY(dataset,id));
        """)
        db.execute("BEGIN IMMEDIATE")
        columns = {c[1] for c in db.execute("PRAGMA table_info(dataset)")}
        for name, default in (("task", "embedding"), ("config", canonical(settings({"query_mode": "template"})))):
            if name not in columns:
                db.execute(f"ALTER TABLE dataset ADD COLUMN {name} TEXT")
                db.execute(f"UPDATE dataset SET {name}=?", (default,))
        asset_columns = {c[1] for c in db.execute("PRAGMA table_info(asset)")}
        if "data" in asset_columns:
            rows = db.execute("SELECT * FROM asset").fetchall()
            db.execute("ALTER TABLE asset RENAME TO asset_inline")
            db.execute("CREATE TABLE asset(owner TEXT,sha TEXT,mime TEXT,object_key TEXT,size INTEGER,name TEXT,metadata TEXT,PRIMARY KEY(owner,sha))")
            for row in rows:
                sha, key = write_object(row["owner"], row["data"], row["mime"])
                db.execute("INSERT INTO asset VALUES(?,?,?,?,?,?,?)", (row["owner"], sha, row["mime"], key, len(row["data"]), sha, "{}"))
            figures = db.execute("SELECT f.*,d.owner FROM figure f JOIN dataset d ON d.id=f.dataset").fetchall()
            for f in figures:
                db.execute(
                    "INSERT OR IGNORE INTO asset_ref VALUES(?,?,?,?,?,?,?)",
                    (f["dataset"], f["owner"], f["sha"], f["doc"], "image", "", canonical({"chunk_id": f["chunk"], "width": f["width"], "height": f["height"]})),
                )
            db.execute("DROP TABLE asset_inline")
        for table in ("figure", "mining"):
            db.execute(f"DROP TABLE IF EXISTS {table}")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='export'").fetchone():
            # Completed downloads remain stored as assets while schema-v2 exports use explicit adapter IDs.
            from .assets import register

            for row in db.execute("SELECT e.*,d.owner FROM export e JOIN dataset d ON d.id=e.dataset").fetchall():
                sha = register(db, row["owner"], row["package"], "application/zip", "published.zip")
                db.execute("INSERT OR IGNORE INTO asset_ref VALUES(?,?,?,?,?,?,?)", (row["dataset"], row["owner"], sha, "", "published_export", "", canonical({"version": row["version"]})))
            db.execute("DROP TABLE export")
        db.execute(
            "CREATE TABLE IF NOT EXISTS export_file(dataset TEXT,version TEXT,adapter TEXT,owner TEXT,sha TEXT,PRIMARY KEY(dataset,version,adapter),FOREIGN KEY(dataset,version) REFERENCES version(dataset,id))"
        )
        for row in db.execute("SELECT dataset,id,body FROM evidence").fetchall():
            item = json.loads(row["body"])
            if "parts" not in item:
                item["parts"] = [{"type": "text", "text": item["text"]}]
                item["sha256"] = digest(item["text"])
                db.execute("UPDATE evidence SET body=? WHERE dataset=? AND id=?", (canonical(item), row["dataset"], row["id"]))
        for row in db.execute("SELECT r.*,d.snapshot FROM revision r JOIN dataset d ON d.id=r.dataset").fetchall():
            old = json.loads(row["body"])
            if old.get("schema_version") == 2:
                continue
            negatives = [dict({k: v for k, v in n.items() if k != "id"}, evidence_id=n["id"]) for n in old["negatives"]]
            sample = {
                "schema_version": 2,
                "sample_id": str(row["id"]),
                "revision": row["rev"],
                "task": "embedding",
                "snapshot_id": row["snapshot"] or "",
                "group_id": old["group_id"],
                "split": old["split"],
                "evidence_ids": old["positives"] + [n["evidence_id"] for n in negatives],
                "provenance": {"query_origin": old["origin"]},
                "payload": {"query": [{"type": "text", "text": old["query"]}], "positives": old["positives"], "negatives": negatives},
            }
            db.execute("UPDATE revision SET body=? WHERE dataset=? AND id=? AND rev=?", (canonical(sample), row["dataset"], row["id"], row["rev"]))
        db.execute("UPDATE dataset SET state='interrupted',error='服务重启，请重新授权继续' WHERE state IN ('queued','running')")


def current_samples(db, ds, limit=None, offset=0):
    sql = """SELECT r.* FROM revision r WHERE dataset=? AND rev=(
           SELECT MAX(n.rev) FROM revision n WHERE n.dataset=r.dataset AND n.id=r.id) ORDER BY id"""
    return db.execute(sql + (" LIMIT ? OFFSET ?" if limit else ""), (ds, limit, offset) if limit else (ds,))


def evidence_map(db, ds):
    return {r["id"]: json.loads(r["body"]) for r in db.execute("SELECT id,body FROM evidence WHERE dataset=?", (ds,))}


def evidence_item(db, ds, eid):
    row = db.execute("SELECT body FROM evidence WHERE dataset=? AND id=?", (ds, eid)).fetchone()
    if not row:
        raise FactoryError("证据不存在")
    return json.loads(row[0])
