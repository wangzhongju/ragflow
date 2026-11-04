"""Tenant-scoped content-addressed assets. SQL stores metadata and object keys only."""

import hashlib
import io
import mimetypes
import os
import tempfile
from pathlib import Path

from .source import FactoryError, canonical


def key(owner, sha):
    return owner + "/" + sha[:2] + "/" + sha


def client():
    from minio import Minio

    return Minio(
        os.environ["FACTORY_MINIO_ENDPOINT"],
        access_key=os.environ["FACTORY_MINIO_ACCESS_KEY"],
        secret_key=os.environ["FACTORY_MINIO_SECRET_KEY"],
        secure=os.getenv("FACTORY_MINIO_SECURE", "false") == "true",
    )


def write_object(owner, data, mime):
    sha = hashlib.sha256(data).hexdigest()
    object_key = key(owner, sha)
    if os.getenv("FACTORY_MINIO_ENDPOINT"):
        conn = client()
        bucket = os.getenv("FACTORY_MINIO_BUCKET", "ragflow-data-factory")
        if not conn.bucket_exists(bucket):
            conn.make_bucket(bucket)
        conn.put_object(bucket, object_key, io.BytesIO(data), len(data), content_type=mime)
    else:
        target = Path(os.environ["FACTORY_ASSET_DIR"]) / object_key
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            stream.write(data)
            temporary = Path(stream.name)
        temporary.replace(target)
    return sha, object_key


def register(db, owner, data, mime, name, metadata=None):
    sha = hashlib.sha256(data).hexdigest()
    if not db.execute("SELECT 1 FROM asset WHERE owner=? AND sha=?", (owner, sha)).fetchone():
        _, object_key = write_object(owner, data, mime)
        db.execute("INSERT INTO asset(owner,sha,mime,object_key,size,name,metadata) VALUES(?,?,?,?,?,?,?)", (owner, sha, mime, object_key, len(data), name, canonical(metadata or {})))
    return sha


def read(db, owner, sha):
    item = db.execute("SELECT * FROM asset WHERE owner=? AND sha=?", (owner, sha)).fetchone()
    if not item:
        raise FactoryError("资产不存在", 404)
    if os.getenv("FACTORY_MINIO_ENDPOINT"):
        response = client().get_object(os.getenv("FACTORY_MINIO_BUCKET", "ragflow-data-factory"), item["object_key"])
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()
    else:
        data = (Path(os.environ["FACTORY_ASSET_DIR"]) / item["object_key"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != sha:
        raise FactoryError("资产校验失败", 409)
    return dict(item), data


def archive_name(item):
    suffix = mimetypes.guess_extension(item["mime"]) or ".bin"
    return "assets/" + item["sha"] + suffix


def relate(db, ds, owner, sha, doc, role, parent=None, locator=None):
    db.execute("INSERT OR IGNORE INTO asset_ref(dataset,owner,sha,doc,role,parent,locator) VALUES(?,?,?,?,?,?,?)", (ds, owner, sha, doc, role, parent or "", canonical(locator or {})))


def collect_unreferenced(db, owner):
    rows = db.execute(
        """SELECT * FROM asset a WHERE owner=? AND NOT EXISTS
        (SELECT 1 FROM asset_ref r WHERE r.owner=a.owner AND r.sha=a.sha) AND NOT EXISTS
        (SELECT 1 FROM export_file e WHERE e.owner=a.owner AND e.sha=a.sha)""",
        (owner,),
    ).fetchall()
    for item in rows:
        if os.getenv("FACTORY_MINIO_ENDPOINT"):
            client().remove_object(os.getenv("FACTORY_MINIO_BUCKET", "ragflow-data-factory"), item["object_key"])
        else:
            (Path(os.environ["FACTORY_ASSET_DIR"]) / item["object_key"]).unlink(missing_ok=True)
        db.execute("DELETE FROM asset WHERE owner=? AND sha=?", (owner, item["sha"]))
    return len(rows)
