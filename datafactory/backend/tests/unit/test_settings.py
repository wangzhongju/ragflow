"""The environment guard refuses a development process aimed at shared production resources."""

import pytest
from pydantic import ValidationError

from datafactory.core.settings import Settings


def test_dev_requires_dev_in_every_resource_name():
    with pytest.raises(ValidationError, match="database"):
        Settings(
            env="dev",
            database_url="mysql+asyncmy://u:p@h/datafactory",
            redis_prefix="df:dev:h:",
            minio_bucket="datafactory-dev-h",
        )


def test_dev_rejects_a_production_bucket():
    with pytest.raises(ValidationError, match="bucket"):
        Settings(
            env="dev",
            database_url="mysql+asyncmy://u:p@h/datafactory_dev_h",
            redis_prefix="df:dev:h:",
            minio_bucket="datafactory",
        )


def test_dev_rejects_a_production_redis_prefix():
    with pytest.raises(ValidationError, match="redis prefix"):
        Settings(
            env="dev",
            database_url="mysql+asyncmy://u:p@h/datafactory_dev_h",
            redis_prefix="df:prod:",
            minio_bucket="datafactory-dev-h",
        )


def test_production_names_are_not_forced_to_contain_dev():
    settings = Settings(
        env="prod",
        database_url="mysql+asyncmy://u:p@h/datafactory",
        redis_prefix="df:prod:",
        minio_bucket="datafactory",
    )
    assert settings.redis_key("runs", "1") == "df:prod:runs:1"


@pytest.mark.parametrize("field", ["minio_bucket", "redis_prefix", "database_url"])
def test_empty_names_do_not_bypass_isolation(field):
    with pytest.raises(ValidationError):
        Settings.model_validate({field: ""})
