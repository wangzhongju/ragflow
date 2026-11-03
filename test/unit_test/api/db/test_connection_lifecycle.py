"""Exercise connection ownership with a real local pool, without runtime services.

Load the owning functions via AST to avoid initializing application settings,
models and search backends when testing database connection cleanup.
"""

import ast
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from peewee import OperationalError
from playhouse.pool import PooledSqliteDatabase

ROOT = Path(__file__).resolve().parents[4]


def _load_function(path, name, db):
    source = ROOT / path
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {
        "DB": db,
        "logging": logging,
        "timer": time.perf_counter,
        "settings": SimpleNamespace(DATABASE_TYPE="MYSQL"),
        "GAUSSDB_COMPATIBLE_DATABASE_TYPES": {"GAUSSDB"},
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)  # noqa: S102 - own source definitions
    return namespace[name]


@pytest.fixture
def db():
    pool = PooledSqliteDatabase(":memory:", max_connections=2, check_same_thread=False)
    yield pool
    pool.close_all()


def test_cleanup_returns_current_connection_and_is_idempotent(db):
    close = _load_function("api/db/db_models.py", "close_connection", db)
    db.execute_sql("SELECT 1").close()
    close()
    assert db.is_closed()
    assert not db._in_use
    close()
    assert db.is_closed()


def test_cleanup_does_not_close_another_workers_old_connection(db):
    close = _load_function("api/db/db_models.py", "close_connection", db)
    ready, cleaned = threading.Event(), threading.Event()

    def worker():
        with db.connection_context():
            conn = db.connection()
            key = db.conn_key(conn)
            # Reproduce a connection checked out >30s without slowing the test.
            with db._pool_lock:
                db._in_use[key] = db._in_use[key]._replace(checked_out=time.time() - 31)
            ready.set()
            assert cleaned.wait(5)
            assert db.connection() is conn
            cursor = db.execute_sql("SELECT 1")
            assert cursor.fetchone() == (1,)
            cursor.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(worker)
        try:
            assert ready.wait(5)
            db.execute_sql("SELECT 1").close()
            close()
        finally:
            cleaned.set()
        result.result(timeout=5)
    assert db.is_closed()
    assert not db._in_use


def test_health_probe_releases_connection_in_its_worker(db):
    check = _load_function("api/utils/health_utils.py", "check_db", db)

    def probe():
        for _ in range(10):
            ok, meta = check()
            assert ok, meta
            assert db.is_closed()
            assert not db._in_use

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(probe).result(timeout=5)


def test_health_probe_returns_connection_after_query_error(db, monkeypatch):
    check = _load_function("api/utils/health_utils.py", "check_db", db)

    def fail(*args, **kwargs):
        db.connection()
        raise OperationalError("probe failed")

    monkeypatch.setattr(db, "execute_sql", fail)
    ok, meta = check()
    assert not ok
    assert meta["error"] == "probe failed"
    assert db.is_closed()
    assert not db._in_use


def test_health_probe_reports_connection_failure(db, monkeypatch):
    check = _load_function("api/utils/health_utils.py", "check_db", db)

    def fail():
        raise OperationalError("connect failed")

    monkeypatch.setattr(db, "_connect", fail)
    ok, meta = check()
    assert not ok
    assert meta["error"] == "connect failed"
    assert db.is_closed()
    assert not db._in_use
