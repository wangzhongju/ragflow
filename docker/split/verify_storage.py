"""Run inside the RAGFlow image: create, verify, or clean isolated storage probes."""

import io
import json
import os
import re
import sys

import pymysql
import valkey
from elasticsearch import Elasticsearch
from minio import Minio


def main():
    phase, probe = sys.argv[1:]
    if phase not in {"create", "verify", "clean"} or not re.fullmatch(r"rfcheck[a-z0-9]{8,32}", probe):
        raise SystemExit("Usage: verify_storage.py {create|verify|clean} rfcheck<8-32 lowercase alphanumeric>")
    env = os.environ
    mysql = pymysql.connect(
        host=env["MYSQL_HOST"], port=int(env["MYSQL_PORT"]), user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"], database=env["MYSQL_DBNAME"], autocommit=True,
    )
    redis = valkey.Valkey(host=env["REDIS_HOST"], password=env["REDIS_PASSWORD"], db=1, decode_responses=True)
    es = Elasticsearch(f'http://{env["ES_HOST"]}:9200', basic_auth=("elastic", env["ELASTIC_PASSWORD"]))
    minio = Minio(f'{env["MINIO_HOST"]}:9000', access_key=env["MINIO_USER"], secret_key=env["MINIO_PASSWORD"], secure=False)
    stream = probe + ":stream"
    try:
        if phase == "create":
            with mysql.cursor() as cursor:
                cursor.execute(f"CREATE TABLE `{probe}` (id INT PRIMARY KEY, value VARCHAR(64))")
                cursor.execute(f"INSERT INTO `{probe}` VALUES (1, %s)", ("initial",))
                cursor.execute(f"UPDATE `{probe}` SET value=%s WHERE id=1", (probe,))
            redis.set(probe, "initial")
            redis.set(probe, probe)
            redis.xgroup_create(stream, "check", id="0", mkstream=True)
            redis.xadd(stream, {"value": probe})
            messages = redis.xreadgroup("check", "verifier", {stream: ">"}, count=1)
            assert messages[0][1][0][1]["value"] == probe
            redis.xack(stream, "check", messages[0][1][0][0])
            es.indices.create(index=probe, settings={"number_of_shards": 1, "number_of_replicas": 0}, mappings={"properties": {"value": {"type": "keyword"}, "vector": {"type": "dense_vector", "dims": 3, "index": True, "similarity": "cosine"}}})
            es.index(index=probe, id="1", document={"value": "initial", "vector": [1.0, 0.0, 0.0]}, refresh=True)
            es.update(index=probe, id="1", doc={"value": probe}, refresh=True)
            minio.make_bucket(probe)
            for payload in (b"initial", probe.encode()):
                minio.put_object(probe, "probe.txt", io.BytesIO(payload), len(payload))
        if phase in {"create", "verify"}:
            with mysql.cursor() as cursor:
                cursor.execute(f"SELECT value FROM `{probe}` WHERE id=1")
                assert cursor.fetchone()[0] == probe
            assert redis.get(probe) == probe
            assert redis.xlen(stream) == 1
            assert redis.xpending(stream, "check")["pending"] == 0
            hits = es.search(index=probe, knn={"field": "vector", "query_vector": [1.0, 0.0, 0.0], "k": 1, "num_candidates": 10})["hits"]["hits"]
            assert hits[0]["_source"]["value"] == probe
            response = minio.get_object(probe, "probe.txt")
            try:
                assert response.read() == probe.encode()
            finally:
                response.close()
                response.release_conn()
        if phase == "clean":
            with mysql.cursor() as cursor:
                cursor.execute(f"DROP TABLE IF EXISTS `{probe}`")
            redis.delete(probe, stream)
            es.indices.delete(index=probe, ignore_unavailable=True)
            if minio.bucket_exists(probe):
                minio.remove_object(probe, "probe.txt")
                minio.remove_bucket(probe)
        print(json.dumps({"phase": phase, "probe": probe, "mysql": "ok", "redis_stream": "ok", "elasticsearch_knn": "ok", "minio": "ok"}))
    finally:
        mysql.close()
        redis.close()
        es.close()


if __name__ == "__main__":
    main()
