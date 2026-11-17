"""The M0 HTTP surface: sign-in, projects, and RAGFlow resources."""

import json

import httpx
import pytest

from datafactory.app.auth import session_cookie
from datafactory.core.settings import GatewaySettings


def _envelope(data, code=0, status=200):
    return httpx.Response(status, json={"code": code, "data": data, "message": ""}, headers={"X-Gateway-Version": "1"})


@pytest.fixture
def gateway(app, monkeypatch):
    """Route every gateway call through ``handler``, set by each test."""

    def install(handler):
        def factory(request, user_id):
            settings: GatewaySettings = GatewaySettings(
                gateway_base_url="http://gateway.test/api/v1", gateway_service_key="secret", gateway_version="1"
            )
            return __import__("datafactory.gateway.client", fromlist=["GatewayClient"]).GatewayClient(
                settings, user_id, transport=httpx.MockTransport(handler)
            )

        monkeypatch.setattr("datafactory.app.routes._gateway", factory)

    return install


async def test_health_reports_the_environment(client):
    response = await client.get("/healthz")
    assert response.json() == {"status": "ok", "env": "dev"}


async def test_requests_without_a_session_are_rejected(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get("/api/factory/v1/projects")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_ragflow_token_bootstraps_the_platform_session(app, gateway):
    gateway(lambda _request: _envelope({"user_id": "u9", "tenant_ids": ["t1"], "nickname": "Ada", "lang": "zh"}))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get("/api/factory/v1/me", headers={"Authorization": "Bearer jwt"})
    assert response.status_code == 200
    assert response.json()["user_id"] == "u9"
    _name, value = session_cookie("u9", app.state.settings.session_secret)
    assert response.headers["set-cookie"].startswith(f"{_name}={value};")


async def test_password_login_establishes_a_session_independent_of_the_ragflow_token(app, gateway):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        assert request.headers["x-df-service-key"] == "secret"
        assert "authorization" not in request.headers
        assert "x-df-user-id" not in request.headers
        assert json.loads(request.content) == {"email": "ada@example.org", "password": "ciphertext"}
        return _envelope({"user_id": "u9", "tenant_ids": ["t1"], "nickname": "Ada", "lang": "zh"})

    gateway(handler)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        login = await http.post("/api/factory/v1/session", json={"email": "ada@example.org", "password": "ciphertext"})
        assert login.status_code == 200
        assert "httponly" in login.headers["set-cookie"].lower()
        assert "authorization" not in login.headers
        me = await http.get("/api/factory/v1/me", headers={"Authorization": "Bearer replaced-token"})
        assert me.status_code == 200
        assert me.json()["user_id"] == "u9"
        assert (await http.get("/api/factory/v1/projects")).status_code == 200
    assert calls == [("POST", "/api/v1/gateway/session")]


async def test_invalid_credentials_do_not_issue_a_platform_cookie(app, gateway):
    gateway(lambda _request: _envelope(None, code=401, status=401))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post(
            "/api/factory/v1/session", json={"email": "ada@example.org", "password": "ciphertext"}
        )
        assert response.status_code == 401
        assert response.json()["code"] == "invalid_credentials"
        assert "set-cookie" not in response.headers
        assert (await http.get("/api/factory/v1/projects")).status_code == 401


@pytest.mark.parametrize(
    ("gateway_status", "status", "code"), [(401, 401, "unauthorized"), (503, 502, "gateway_unavailable")]
)
async def test_sign_in_distinguishes_rejected_tokens_from_gateway_failures(app, gateway, gateway_status, status, code):
    gateway(lambda _request: httpx.Response(gateway_status, json={"code": gateway_status, "message": "Session error"}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get("/api/factory/v1/me", headers={"Authorization": "Bearer expired"})
    assert response.status_code == status
    assert response.json()["code"] == code
    assert "set-cookie" not in response.headers


async def test_project_lifecycle(client):
    created = await client.post("/api/factory/v1/projects", json={"name": "Laws", "description": "statutes"})
    assert created.status_code == 201
    project_id = created.json()["id"]
    assert project_id.startswith("prj_")

    listed = await client.get("/api/factory/v1/projects")
    assert [item["id"] for item in listed.json()] == [project_id]

    renamed = await client.patch(f"/api/factory/v1/projects/{project_id}", json={"name": "Regulations"})
    assert renamed.json()["name"] == "Regulations"

    members = await client.put(
        f"/api/factory/v1/projects/{project_id}/members",
        json=[{"user_id": "u1", "role": "owner"}, {"user_id": "u2", "role": "reviewer"}],
    )
    assert members.status_code == 200
    assert {item["role"] for item in members.json()} == {"owner", "reviewer"}

    removed = await client.delete(f"/api/factory/v1/projects/{project_id}")
    assert removed.status_code == 204
    assert (await client.get("/api/factory/v1/projects")).json() == []


async def test_repeating_a_create_with_the_same_key_returns_the_same_project(client):
    headers = {"Idempotency-Key": "create-1"}
    body = {"name": "Laws", "description": ""}
    first = await client.post("/api/factory/v1/projects", json=body, headers=headers)
    second = await client.post("/api/factory/v1/projects", json=body, headers=headers)
    assert first.json()["id"] == second.json()["id"]
    assert len((await client.get("/api/factory/v1/projects")).json()) == 1


async def test_reusing_a_key_for_a_different_body_conflicts(client):
    headers = {"Idempotency-Key": "create-2"}
    await client.post("/api/factory/v1/projects", json={"name": "Laws"}, headers=headers)
    again = await client.post("/api/factory/v1/projects", json={"name": "Other"}, headers=headers)
    assert again.status_code == 409
    assert again.json()["code"] == "conflict"


async def test_datasets_and_models_come_from_the_gateway(client, gateway):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/datasets"):
            return _envelope(
                [
                    {
                        "id": "kb1",
                        "name": "Laws",
                        "tenant_id": "t1",
                        "embd_id": "e@f",
                        "vector_dim": 768,
                        "parser_id": "naive",
                        "doc_num": 2,
                        "chunk_num": 10,
                    }
                ]
            )
        return _envelope(
            [
                {
                    "model_id": "chat@openai",
                    "tenant_id": "t1",
                    "type": ["chat"],
                    "factory": "openai",
                    "name": "gpt",
                    "max_tokens": 8192,
                    "capabilities": {"vision": False},
                }
            ]
        )

    gateway(handler)
    datasets = await client.get("/api/factory/v1/ragflow/datasets")
    assert datasets.json()[0]["vector_dim"] == 768
    models = await client.get("/api/factory/v1/ragflow/models", params={"types": "chat"})
    assert models.json()[0]["model_id"] == "chat@openai"
    assert "api_key" not in json.dumps(models.json())


async def test_a_foreign_knowledge_base_is_forbidden(client, gateway):
    gateway(lambda _request: _envelope(None, code=108, status=200))
    response = await client.get("/api/factory/v1/ragflow/datasets/kb-foreign/documents")
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
