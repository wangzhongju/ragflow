"""HTTP contract tests; authentication and native parsing are isolated stubs."""

import asyncio
import importlib.util
import io
import sys
from functools import wraps
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from quart import Blueprint, Quart, jsonify, request
from werkzeug.datastructures import FileStorage, MultiDict
from werkzeug.test import EnvironBuilder

ROOT = Path(__file__).resolve().parents[5]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def endpoint(monkeypatch):
    calls = []
    service = load("parse_service_test", "api/apps/services/file_parse_service.py")
    monkeypatch.setitem(sys.modules, "api.apps.services.file_parse_service", service)
    apps = ModuleType("api.apps")
    apps.AUTH_API = "API"
    apps.current_user = SimpleNamespace(id="tenant-a")

    def login_required(*, auth_types):
        assert auth_types == ["API"]

        def decorate(fn):
            @wraps(fn)
            async def wrapped(*args, **kwargs):
                if request.headers.get("Authorization") != "Bearer test-key":
                    return jsonify(code=401), 401
                return await fn(*args, **kwargs)

            return wrapped

        return decorate

    apps.login_required = login_required
    monkeypatch.setitem(sys.modules, "api.apps", apps)
    utils = ModuleType("api.utils.api_utils")
    utils.get_result = lambda **kwargs: jsonify({"code": 0, **kwargs})
    monkeypatch.setitem(sys.modules, "api.utils.api_utils", utils)
    misc = ModuleType("common.misc_utils")

    async def execute(fn, *args):
        return fn(*args)

    misc.thread_pool_exec_long_time = execute
    monkeypatch.setitem(sys.modules, "common.misc_utils", misc)
    storage = ModuleType("api.db.services.file_service")

    def parse(*args, **kwargs):
        calls.append((args, kwargs))
        return "parsed document"

    storage.FileService = SimpleNamespace(parse=parse)
    monkeypatch.setitem(sys.modules, "api.db.services.file_service", storage)
    spec = importlib.util.spec_from_file_location("parse_api_test", ROOT / "api/apps/restful_apis/file_parse_api.py")
    module = importlib.util.module_from_spec(spec)
    module.manager = Blueprint("parsing", __name__)
    spec.loader.exec_module(module)
    app = Quart(__name__)
    app.register_blueprint(module.manager, url_prefix="/api/v1")
    return app, module, calls


def send(endpoint, filename="sample.txt", blob=b"hello", form=None, auth=True):
    async def run():
        client = endpoint[0].test_client()
        data = MultiDict(form or {})
        data.add("file", (io.BytesIO(blob), filename))
        builder = EnvironBuilder(method="POST", data=data)
        environ = builder.get_environ()
        headers = {"Content-Type": environ["CONTENT_TYPE"]}
        if auth:
            headers["Authorization"] = "Bearer test-key"
        response = await client.post(
            "/api/v1/files/parse",
            headers=headers,
            data=environ["wsgi.input"].read(),
        )
        environ["wsgi.input"].close()
        builder.close()
        return response.status_code, await response.get_json()

    return asyncio.run(run())


def test_success_and_tenant(endpoint):
    status, body = send(endpoint, filename="/temp/report.TXT", form={"layout_recognize": "DeepDOC"})
    assert status == 200 and body["code"] == 0
    assert body["data"]["filename"] == "report.TXT"
    assert body["data"]["content"] == "parsed document"
    assert endpoint[2] == [(("report.TXT", b"hello"), {"img_base64": False, "tenant_id": "tenant-a", "layout_recognize": "DeepDOC"})]


def test_windows_filename():
    service = load("parse_service_names", "api/apps/services/file_parse_service.py")
    assert service.validate_options("C:\\temp\\report.TXT", "Plain Text") == "report.TXT"


@pytest.mark.parametrize(
    "kwargs,status",
    [
        ({"auth": False}, 401),
        ({"blob": b""}, 400),
        ({"filename": "payload.exe"}, 400),
        ({"form": {"layout_recognize": "remote-model"}}, 400),
        ({"form": {"url": "http://localhost"}}, 400),
        ({"form": MultiDict([("layout_recognize", "DeepDOC"), ("layout_recognize", "Plain Text")])}, 400),
        ({"blob": b"x" * (20 * 1024 * 1024 + 1)}, 413),
    ],
)
def test_rejects_invalid_input(endpoint, kwargs, status):
    assert send(endpoint, **kwargs)[0] == status
    assert not endpoint[2]


def test_parser_error_is_not_exposed(endpoint, monkeypatch):
    def fail(*args):
        raise RuntimeError("private credential")

    monkeypatch.setattr(endpoint[1], "parse_document", fail)
    status, body = send(endpoint)
    assert status == 422 and "private credential" not in str(body)


def test_discovery_and_wrong_content_type(endpoint):
    async def run():
        client = endpoint[0].test_client()
        headers = {"Authorization": "Bearer test-key"}
        response = await client.get("/api/v1/files/parse", headers=headers)
        assert (await response.get_json())["data"]["max_file_bytes"] == 20 * 1024 * 1024
        response = await client.post("/api/v1/files/parse", headers=headers, json={"url": "http://localhost"})
        assert response.status_code == 415
        response = await client.post(
            "/api/v1/files/parse",
            headers=headers,
            form={"layout_recognize": "DeepDOC"},
            files={
                "file": FileStorage(io.BytesIO(b"one"), filename="one.txt"),
                "extra": FileStorage(io.BytesIO(b"two"), filename="two.txt"),
            },
        )
        assert response.status_code == 400

    asyncio.run(run())
