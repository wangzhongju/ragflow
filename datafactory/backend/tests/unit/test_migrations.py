"""Run the real migration chain against an isolated temporary database."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

from datafactory.store.tables import Base


def test_upgrade_downgrade_and_runtime_columns_agree(tmp_path):
    root = Path(__file__).resolve().parents[2]
    database = tmp_path / "datafactory_dev_migrations.db"
    env = {
        **os.environ,
        "DF_ENV": "dev",
        "DF_DATABASE_URL": f"sqlite+aiosqlite:///{database.as_posix()}",
        "DF_MINIO_BUCKET": "datafactory-dev-test",
        "DF_REDIS_PREFIX": "df:dev:test:",
        "PYTHONPATH": str(root / "src"),
    }
    for operation in (("upgrade", "head"), ("downgrade", "0003_production"), ("upgrade", "head")):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *operation], cwd=root, env=env, capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, result.stdout + result.stderr
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    try:
        schema = inspect(engine)
        assert set(schema.get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
        for name, table in Base.metadata.tables.items():
            assert {column["name"] for column in schema.get_columns(name)} == set(table.columns.keys()), name
    finally:
        engine.dispose()
