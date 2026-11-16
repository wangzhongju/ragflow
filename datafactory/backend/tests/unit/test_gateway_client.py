"""The gateway client against a scripted transport: no socket, the real contract."""

import json

import httpx
import pytest

from datafactory.core.errors import GatewayUnavailable, GatewayVersionMismatch
from datafactory.core.settings import GatewaySettings
from datafactory.gateway.client import GatewayClient

_BASE = "http://gateway.test/api/v1"


def _client(handler) -> GatewayClient:
    settings = GatewaySettings(gateway_base_url=_BASE, gateway_service_key="secret", gateway_version="1")
    return GatewayClient(settings, user_id="u1", request_id="req-1", transport=httpx.MockTransport(handler))


def _envelope(data, code=0, message="", status=200, version="1"):
    return httpx.Response(
        status, json={"code": code, "data": data, "message": message}, headers={"X-Gateway-Version": version}
    )


def test_headers_carry_the_service_key_and_the_user():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers["x-df-service-key"]
        seen["user"] = request.headers["x-df-user-id"]
        seen["request"] = request.headers["x-df-request-id"]
        return _envelope([])

    import asyncio

    asyncio.run(_client(handler).list_datasets())
    assert seen == {"key": "secret", "user": "u1", "request": "req-1"}


async def test_session_uses_the_browser_token_instead_of_the_service_key():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer jwt"
        assert "x-df-service-key" not in request.headers
        return _envelope({"user_id": "u1", "tenant_ids": ["t2", "t1"], "nickname": "Ada", "lang": "zh"})

    session = await _client(handler).session_from_token("Bearer jwt")
    assert session.tenant_ids == ["t2", "t1"]


async def test_a_different_contract_version_is_refused():
    def handler(_request: httpx.Request) -> httpx.Response:
        return _envelope([], version="2")

    with pytest.raises(GatewayVersionMismatch):
        await _client(handler).list_datasets()


async def test_gateway_permission_error_keeps_its_code():
    def handler(_request: httpx.Request) -> httpx.Response:
        return _envelope(None, code=108, message="no access", status=200)

    with pytest.raises(GatewayUnavailable) as caught:
        await _client(handler).list_documents("kb-foreign")
    assert caught.value.gateway_code == 108


async def test_rate_limit_is_reported():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"code": 429, "message": "slow down"})

    with pytest.raises(GatewayUnavailable) as caught:
        await _client(handler).list_models()
    assert caught.value.gateway_code == 429


async def test_scan_checks_the_eof_count():
    lines = [
        json.dumps({"chunk_id": "c1", "doc_id": "d1", "kb_id": "kb", "content": "a", "doc_type": "text"}),
        json.dumps({"_eof": True, "doc_id": "d1", "count": 2}),
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content="\n".join(lines) + "\n", headers={"X-Gateway-Version": "1"})

    chunks = []
    with pytest.raises(GatewayUnavailable, match="reported 2"):
        async for chunk in _client(handler).scan_chunks("kb", ["d1"]):
            chunks.append(chunk)
    assert [chunk.chunk_id for chunk in chunks] == ["c1"]


async def test_scan_rejects_a_stream_that_ends_without_eof():
    line = json.dumps({"chunk_id": "c1", "doc_id": "d1", "kb_id": "kb", "content": "a", "doc_type": "text"})

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=line + "\n", headers={"X-Gateway-Version": "1"})

    with pytest.raises(GatewayUnavailable, match="before EOF"):
        async for _chunk in _client(handler).scan_chunks("kb", ["d1"]):
            pass


async def test_scan_accepts_a_complete_stream():
    lines = [
        json.dumps({"chunk_id": "c1", "doc_id": "d1", "kb_id": "kb", "content": "a", "doc_type": "text"}),
        json.dumps({"_eof": True, "doc_id": "d1", "count": 1}),
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content="\n".join(lines) + "\n", headers={"X-Gateway-Version": "1"})

    chunks = [chunk async for chunk in _client(handler).scan_chunks("kb", ["d1"])]
    assert chunks[0].content == "a"


async def test_dense_search_returns_hits_with_their_dimension():
    def handler(_request: httpx.Request) -> httpx.Response:
        return _envelope({"dim": 3, "hits": [{"chunk_id": "c1", "doc_id": "d1", "score": 0.9}]})

    found = await _client(handler).search_dense(["kb"], {"vector": [0.1, 0.2, 0.3]}, top_k=5)
    assert found.dim == 3
    assert found.hits[0].score == 0.9


@pytest.mark.parametrize(
    "lines",
    [
        [],
        [{"_eof": True, "doc_id": "d1", "count": 0}],
        [{"_eof": True, "doc_id": "other", "count": 0}],
        [{"_eof": True, "doc_id": "d1", "count": 0}, {"_eof": True, "doc_id": "d1", "count": 0}],
    ],
)
async def test_scan_rejects_missing_documents_foreign_eof_and_duplicate_eof(lines):
    def handler(_request):
        return httpx.Response(200, content="\n".join(json.dumps(line) for line in lines))

    with pytest.raises(GatewayUnavailable):
        _ = [chunk async for chunk in _client(handler).scan_chunks("kb", ["d1", "d2"])]


async def test_scan_checks_all_1026_chunks_and_empty_document_eof():
    lines = [
        json.dumps({"chunk_id": f"c{i}", "doc_id": "d1", "kb_id": "kb", "content": "x", "doc_type": "text"})
        for i in range(1026)
    ]
    lines.extend(
        [
            json.dumps({"_eof": True, "doc_id": "d1", "count": 1026}),
            json.dumps({"_eof": True, "doc_id": "d2", "count": 0}),
        ]
    )
    client = _client(lambda _: httpx.Response(200, content="\n".join(lines)))
    chunks = [chunk async for chunk in client.scan_chunks("kb", ["d1", "d2"])]
    assert len(chunks) == 1026
