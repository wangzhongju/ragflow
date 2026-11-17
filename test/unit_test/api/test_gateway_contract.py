#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
"""Contract tests for the corpus gateway.

The gateway composes existing RAGFlow services and owns no tables, so these
tests stub those services and exercise the contract the DataFactory platform
depends on: the service key, per-user access, cursor paging, vector dimension
detection, and model-call accounting.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SERVICE_KEY = "test-service-key"
USER_ID = "user-1"
OTHER_USER = "user-2"


def _run(coro):
    return asyncio.run(coro)


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.headers = {}

    def get_json(self):
        return self._payload


def _json_result(code=0, message="success", data=None):
    return _Response({"code": code, "message": message, "data": data})


class _Request:
    def __init__(self, headers=None, args=None, body=None):
        self.headers = headers or {}
        self.args = args or {}
        self._body = body

    async def get_json(self, force=True, silent=True):
        return self._body


class _KB:
    def __init__(self, kb_id="kb1", tenant_id="tenant-1", embd_id="embd-1", chunk_num=2, owner=USER_ID):
        self.id = kb_id
        self.tenant_id = tenant_id
        self.embd_id = embd_id
        self.tenant_embd_id = ""
        self.chunk_num = chunk_num
        self.owner = owner
        self.similarity_threshold = 0.2
        self.vector_similarity_weight = 0.3


class _Doc:
    def __init__(self, doc_id, kb_id="kb1"):
        self.id = doc_id
        self.kb_id = kb_id


class _Model:
    def __init__(self, model_id, tenant_id, bit, name="embed"):
        self.id = model_id
        self.provider_id = f"provider-{tenant_id}"
        self.instance_id = f"instance-{tenant_id}"
        self.model_type = bit
        self.status = "active"
        self.model_name = name
        self.extra = '{"max_tokens": 4096}'


class _Store:
    """In-memory stand-in for the knowledge base, document, and model services."""

    def __init__(self):
        self.kbs = {
            "kb1": _KB("kb1"),
            "kbforeign": _KB("kbforeign", tenant_id="tenant-9", owner=OTHER_USER),
        }
        self.docs = {
            "doc-a": {"id": "doc-a", "name": "a.pdf", "suffix": "pdf", "type": "pdf", "size": 10, "content_hash": "ha", "chunk_num": 2, "token_num": 20, "run": "3", "progress": 1, "status": "1", "update_time": 1, "parser_id": "naive", "pipeline_id": ""},
            "doc-b": {"id": "doc-b", "name": "b.pdf", "suffix": "pdf", "type": "pdf", "size": 11, "content_hash": "hb", "chunk_num": 1, "token_num": 8, "run": "3", "progress": 1, "status": "1", "update_time": 2, "parser_id": "naive", "pipeline_id": ""},
            "doc-c": {"id": "doc-c", "name": "c.pdf", "suffix": "pdf", "type": "pdf", "size": 12, "content_hash": "hc", "chunk_num": 0, "token_num": 0, "run": "3", "progress": 1, "status": "1", "update_time": 3, "parser_id": "naive", "pipeline_id": ""},
        }
        self.chunks = {
            "chk-1": {"id": "chk-1", "doc_id": "doc-a", "kb_id": "kb1", "content_with_weight": "alpha", "available_int": 1, "position_int": [[1, 0, 10, 0, 5]], "q_4_vec": [1.0, 0.0, 0.0, 0.0]},
            "chk-2": {"id": "chk-2", "doc_id": "doc-a", "kb_id": "kb1", "content_with_weight": "beta", "available_int": 0, "position_int": [[1, 0, 10, 6, 9]], "q_4_vec": [0.0, 1.0, 0.0, 0.0]},
        }
        self.models = {"model-embed": _Model("model-embed", "tenant-1", 1 << 1), "model-chat": _Model("model-chat", "tenant-1", 1 << 0, name="chat")}
        self.providers = {f"provider-{tenant}": SimpleNamespace(id=f"provider-{tenant}", tenant_id=tenant, provider_name="openai") for tenant in ("tenant-1", "tenant-9")}
        self.instances = {f"instance-{tenant}": SimpleNamespace(id=f"instance-{tenant}", provider_id=f"provider-{tenant}", status="active") for tenant in ("tenant-1", "tenant-9")}
        self.members = {USER_ID: ["tenant-1"]}
        self.vector_reads = []

    def accessible(self, kb_id, user_id):
        kb = self.kbs.get(kb_id)
        return bool(kb) and kb.owner == user_id


STORE = _Store()


def _install(monkeypatch, name, **attrs):
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _load(monkeypatch):
    """Load the gateway modules against stubbed RAGFlow dependencies."""
    repo = Path(__file__).resolve().parents[3]

    class _RetCode:
        SUCCESS = 0
        ARGUMENT_ERROR = 101
        DATA_ERROR = 102
        PERMISSION_ERROR = 108
        AUTHENTICATION_ERROR = 109
        UNAUTHORIZED = 401
        EXCEPTION_ERROR = 100
        SERVER_ERROR = 500
        NOT_FOUND = 404

    # Use the real enums. The bit positions decide which model type an operation
    # is allowed to call, so a hand-written stand-in would pass tests that the
    # running service would reject.
    sys.path.insert(0, str(repo))
    from common.constants import LLMType as _RealLLMType
    from common.constants import ModelTypeBinary as _RealBits

    _install(monkeypatch, "common.constants", RetCode=_RetCode, LLMType=_RealLLMType, ModelTypeBinary=_RealBits)
    _install(monkeypatch, "common")

    class _DocStore:
        def get(self, chunk_id, index_name, kb_ids):
            return STORE.chunks.get(chunk_id, {})

        def search(self, fields, highlight, condition, matches, order, offset, limit, idx_names, kb_ids):
            hits = []
            for chunk_id, chunk in STORE.chunks.items():
                if chunk["kb_id"] not in kb_ids:
                    continue
                if condition.get("doc_id") and chunk["doc_id"] not in condition["doc_id"]:
                    continue
                if condition.get("img_id") and chunk.get("img_id") != condition["img_id"]:
                    continue
                excluded = condition.get("must_not", {}).get("id", [])
                if chunk_id in excluded:
                    continue
                hits.append({"_id": chunk_id, "_score": 0.9 if chunk_id == "chk-1" else 0.4, "_source": chunk})
            hits.sort(key=lambda item: item["_score"], reverse=True)
            return {"hits": {"hits": hits[:limit], "total": {"value": len(hits)}}}

        def get_total(self, result):
            return result["hits"]["total"]["value"]

        def get_fields(self, res, fields):
            out = {}
            for hit in res["hits"]["hits"]:
                out[hit["_id"]] = {field: hit["_source"].get(field, "") for field in fields}
            return out

        def get_scores(self, res):
            return {hit["_id"]: hit["_score"] for hit in res["hits"]["hits"]}

    _install(monkeypatch, "common.settings", docStoreConn=_DocStore(), retriever=SimpleNamespace(), STORAGE_IMPL=SimpleNamespace(get=lambda bucket, key: b"\x89PNG\r\n\x1a\n"))

    class _Dealer:
        def __init__(self, store):
            self.dataStore = store

        def chunk_list(self, doc_id, tenant_id, kb_ids, max_count=1024, offset=0, fields=None, sort_by_position=False):
            rows = [chunk for chunk in STORE.chunks.values() if chunk["doc_id"] == doc_id]
            return [{key: value for key, value in row.items() if key == "id" or key in (fields or [])} for row in rows[offset:max_count]]

        async def fetch_chunk_vectors(self, chunk_ids, tenant_id, kb_ids, dim):
            STORE.vector_reads.append(list(chunk_ids))
            return {chunk_id: STORE.chunks[chunk_id][f"q_{dim}_vec"] for chunk_id in chunk_ids if chunk_id in STORE.chunks}

    _install(monkeypatch, "rag.nlp.search", Dealer=_Dealer, index_name=lambda tenant: f"ragflow_{tenant}")
    _install(monkeypatch, "rag.nlp")
    _install(monkeypatch, "rag")

    class _KnowledgebaseService:
        @staticmethod
        def accessible(kb_id, user_id):
            return STORE.accessible(kb_id, user_id)

        @staticmethod
        def get_by_id(kb_id):
            kb = STORE.kbs.get(kb_id)
            return (True, kb) if kb else (False, None)

        @staticmethod
        def get_by_tenant_ids(tenant_ids, user_id, *_args):
            rows = [
                {"id": kb.id, "name": kb.id, "tenant_id": kb.tenant_id, "embd_id": kb.embd_id, "tenant_embd_id": "", "parser_id": "naive", "pipeline_id": "", "doc_num": 3, "chunk_num": kb.chunk_num, "similarity_threshold": 0.2, "vector_similarity_weight": 0.3, "parser_config": {"filename_embd_weight": 0.25}}
                for kb in STORE.kbs.values()
                if kb.tenant_id in tenant_ids and kb.owner == user_id
            ]
            return rows, len(rows)

    class _DocumentService:
        @staticmethod
        def get_by_kb_id(kb_id, page, size, orderby, desc, keywords, run_status, types, suffix, doc_ids=None):
            rows = [dict(doc) for doc in STORE.docs.values() if doc_ids is None or doc["id"] in doc_ids]
            rows.sort(key=lambda doc: doc["id"])
            return rows, len(rows)

        @staticmethod
        def get_by_id(doc_id):
            doc = STORE.docs.get(doc_id)
            return (True, _Doc(doc_id)) if doc else (False, None)

    _install(monkeypatch, "api.db.services.knowledgebase_service", KnowledgebaseService=_KnowledgebaseService)
    _install(monkeypatch, "api.db.services.document_service", DocumentService=_DocumentService)

    class _Column:
        def __init__(self, name):
            self.name = name

        def __eq__(self, other):
            return _Eq(other)

        def in_(self, _values):
            return self

    class _TenantModel:
        id = _Column("id")

        @staticmethod
        def get_or_none(condition):
            return STORE.models.get(getattr(condition, "value", None))


    class _Eq:
        def __init__(self, value):
            self.value = value

    class _UserTenant:
        tenant_id = _Column("tenant_id")
        user_id = _Column("user_id")

        @staticmethod
        def select(*_args):
            return _UserTenant

        @staticmethod
        def where(condition):
            user_id = getattr(condition, "value", USER_ID)
            return [SimpleNamespace(tenant_id=tenant) for tenant in STORE.members.get(user_id, [])]
    _install(monkeypatch, "api.db.db_models", Document=_Doc, TenantModel=_TenantModel, UserTenant=_UserTenant)
    _install(monkeypatch, "api.db.services.tenant_model_provider_service", TenantModelProviderService=SimpleNamespace(
        get_by_tenant_id=lambda tenant: [provider for provider in STORE.providers.values() if provider.tenant_id == tenant],
        get_by_id=lambda identifier: (identifier in STORE.providers, STORE.providers.get(identifier)),
    ))
    _install(monkeypatch, "api.db.services.tenant_model_instance_service", TenantModelInstanceService=SimpleNamespace(
        get_all_by_provider_id=lambda identifier: [instance for instance in STORE.instances.values() if instance.provider_id == identifier],
        get_by_id=lambda identifier: (identifier in STORE.instances, STORE.instances.get(identifier)),
    ))
    _install(monkeypatch, "api.db.services.tenant_model_service", TenantModelService=SimpleNamespace(
        get_models_by_instance_id=lambda identifier: [model for model in STORE.models.values() if model.instance_id == identifier],
    ))

    class _Bundle:
        def __init__(self, tenant_id, config):
            self.config = config

        async def async_chat(self, system, history, gen_conf):
            return "<think>hidden</think>answer"

        def encode(self, texts):
            return [[float(len(text)), 0.0] for text in texts], 7

        def encode_queries(self, text):
            return [0.5, 0.5], 3

        def similarity(self, query, texts):
            return [0.8 for _ in texts], 5

        def describe(self, image):
            return "a diagram"

        def describe_with_prompt(self, image, prompt):
            return prompt

        def transcription(self, audio):
            return "spoken"

    _install(monkeypatch, "api.db.services.llm_service", LLMBundle=_Bundle)
    _install(monkeypatch, "api.db.joint_services.tenant_model_service", resolve_model_config=lambda tenant, kind, model_id: {"llm_factory": "openai", "llm_name": model_id, "model_type": kind}, resolve_model_id=lambda tenant, kind, reference: None)
    _install(monkeypatch, "api.db.services.user_service", TenantService=SimpleNamespace(get_by_id=lambda tenant: (False, None)), UserService=SimpleNamespace(query_user=lambda *_args: pytest.fail("Unexpected credential verification")))
    _install(monkeypatch, "api.utils.crypt", CryptPayloadError=ValueError, decrypt=lambda _value: "encoded-password")
    _install(monkeypatch, "common.doc_store.doc_store_base", MatchDenseExpr=lambda *args, **kwargs: SimpleNamespace(args=args), OrderByExpr=lambda: SimpleNamespace())
    _install(monkeypatch, "common.llm_request_context", normalize_llm_user_id=lambda value: value, set_llm_request_context=lambda **kwargs: "token", reset_llm_request_context=lambda token: None)

    async def _thread_pool_exec(func, *args, **kwargs):
        return func(*args, **kwargs)

    _install(monkeypatch, "common.misc_utils", thread_pool_exec=_thread_pool_exec)
    _install(monkeypatch, "rag.utils.base64_image", parse_storage_composite_id=lambda img_id: img_id.split("-", 1) if "-" in img_id else None)

    service_path = repo / "api" / "apps" / "services" / "gateway_service.py"
    spec = importlib.util.spec_from_file_location("gateway_service_under_test", service_path)
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)

    _install(monkeypatch, "api.utils.api_utils", get_json_result=_json_result)
    _install(monkeypatch, "api.apps", AUTH_JWT="jwt", login_required=lambda **kwargs: (lambda func: func))
    _install(monkeypatch, "api.apps.services", gateway_service=service)
    quart = _install(monkeypatch, "quart", Response=_Response, request=_Request(), g=SimpleNamespace(user=SimpleNamespace(id=USER_ID, nickname="Ada", email="a@b.c", language="zh")))

    route_path = repo / "api" / "apps" / "restful_apis" / "gateway_api.py"
    route_spec = importlib.util.spec_from_file_location("gateway_api_under_test", route_path)
    routes = importlib.util.module_from_spec(route_spec)

    class _Manager:
        def route(self, *_args, **_kwargs):
            return lambda func: func

    # register_page injects manager before the module body runs. Set it on the
    # module before exec so the decorators bind during import.
    sys.modules["gateway_api_under_test"] = routes
    routes.manager = _Manager()
    route_spec.loader.exec_module(routes)
    return service, routes, quart


@pytest.fixture
def gateway(monkeypatch):
    global STORE
    STORE = _Store()
    monkeypatch.setenv("DATAFACTORY_SERVICE_KEY", SERVICE_KEY)
    STORE.vector_reads.clear()
    return _load(monkeypatch)


def test_gateway_disabled_without_service_key(monkeypatch):
    monkeypatch.delenv("DATAFACTORY_SERVICE_KEY", raising=False)
    service, _routes, _quart = _load(monkeypatch)
    assert service.gateway_enabled() is False


def test_service_key_rejects_missing_and_wrong_key(gateway):
    service, routes, quart = gateway
    quart.request.headers = {}
    assert _run(routes._guard())[1] == 403
    quart.request.headers = {service.SERVICE_KEY_HEADER: "nope"}
    assert _run(routes._guard())[1] == 403
    quart.request.headers = {service.SERVICE_KEY_HEADER: SERVICE_KEY, service.USER_HEADER: USER_ID}
    assert _run(routes._guard()) is None


def test_foreign_knowledge_base_is_rejected(gateway):
    service, _routes, _quart = gateway
    with pytest.raises(service.GatewayError) as caught:
        service.list_documents(USER_ID, "kbforeign", None, None, 10)
    assert caught.value.code == 108


def test_dataset_list_reports_vector_dimension_and_hides_other_users(gateway):
    service, _routes, _quart = gateway
    rows = service.list_datasets(USER_ID)
    assert [row["id"] for row in rows] == ["kb1"]
    assert rows[0]["vector_dim"] == 4
    assert "tenant_embd_id" in rows[0]
    assert rows[0]["filename_embd_weight"] == 0.25


def test_document_cursor_walks_every_row_once(gateway):
    service, _routes, _quart = gateway
    seen = []
    cursor = None
    pages = 0
    while True:
        page = service.list_documents(USER_ID, "kb1", None, cursor, 2)
        pages += 1
        seen.extend(doc["id"] for doc in page["documents"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == ["doc-a", "doc-b", "doc-c"]
    assert pages == 2
    assert service.list_documents(USER_ID, "kb1", None, None, 2)["total"] == 3


def test_scan_pages_without_skipping_and_can_attach_vectors(gateway):
    service, _routes, _quart = gateway
    service.SCAN_BATCH_SIZE = 1
    first = service.scan_batch("tenant-1", "kb1", "doc-a", 0, None)
    second = service.scan_batch("tenant-1", "kb1", "doc-a", 1, None)
    assert [row["chunk_id"] for row in first + second] == ["chk-1", "chk-2"]
    assert all(row["kb_id"] == "kb1" and row["doc_id"] == "doc-a" for row in first + second)
    assert first[0]["bbox"] == [0.0, 0.0, 10.0, 5.0]
    attached = _run(service.attach_vectors("tenant-1", "kb1", first))
    assert attached[0]["vector"] == [1.0, 0.0, 0.0, 0.0]
    assert attached[0]["vector_dim"] == 4
    assert STORE.vector_reads == [["chk-1"]]


def test_scan_custom_projection_keeps_required_identity(gateway):
    service, _, _ = gateway
    row = service.scan_batch("tenant-1", "kb1", "doc-a", 0, ["content_with_weight"])[0]
    assert (row["chunk_id"], row["doc_id"], row["kb_id"]) == ("chk-1", "doc-a", "kb1")


def test_models_use_provider_ownership_and_active_instance(gateway):
    service, _, _ = gateway
    STORE.models["foreign"] = _Model("foreign", "tenant-9", 1 << 1)
    models = service.list_models(USER_ID, ["embedding"])
    assert [model["model_id"] for model in models] == ["model-embed"]
    assert models[0]["tenant_id"] == "tenant-1"
    assert models[0]["factory"] == "openai"
    assert models[0]["name"] == "embed"
    assert models[0]["max_tokens"] == 4096
    STORE.instances["instance-tenant-1"].status = "inactive"
    assert service.list_models(USER_ID, None) == []
    with pytest.raises(service.GatewayError, match="not active"):
        _run(service.invoke_model(USER_ID, "model-chat", service.OP_CHAT, {}, None))


def test_dataset_resolves_embedding_id_from_current_reference(gateway):
    service, _, _ = gateway
    STORE.kbs["kb1"].embd_id = "model-embed"
    assert service.list_datasets(USER_ID)[0]["tenant_embd_id"] == "model-embed"


def test_dense_search_returns_scores_and_rejects_a_short_query_vector(gateway):
    service, _routes, _quart = gateway
    found = _run(service.search_dense(USER_ID, ["kb1"], {"vector": [1, 0, 0, 0]}, 5, {"exclude_chunk_ids": ["chk-2"]}, 0.5))
    assert found["dim"] == 4
    assert [hit["chunk_id"] for hit in found["hits"]] == ["chk-1"]
    with pytest.raises(service.GatewayError) as caught:
        _run(service.search_dense(USER_ID, ["kb1"], {"vector": [1, 0]}, 5, None, 0.0))
    assert caught.value.code == 101


def test_dense_scores_accept_client_response_objects(gateway):
    service, _, _ = gateway
    from collections import UserDict
    response = UserDict({"hits": {"hits": [{"_id": "chunk", "_score": 0.91}]}})
    dealer = service.search.Dealer(service.settings.docStoreConn)
    assert service._knn_hits(dealer, response) == [("chunk", 0.91)]


def test_dense_scores_read_named_dataframe_columns(gateway):
    service, _, _ = gateway
    class Frame(dict):
        columns = ("id", "_score")
    frame = Frame(id=["a", "b"], _score=[0.3, 0.8])
    assert service._knn_hits(SimpleNamespace(dataStore=object()), (frame, 2)) == [("b", 0.8), ("a", 0.3)]


def test_model_invoke_accounts_tokens_and_refuses_another_tenants_model(gateway):
    service, _routes, _quart = gateway
    embedded = _run(service.invoke_model(USER_ID, "model-embed", service.OP_EMBED_DOCUMENTS, {"texts": ["ab", "cd"]}, None))
    assert embedded["usage"]["total_tokens"] == 7
    assert embedded["outputs"]["vectors"] == [[2.0, 0.0], [2.0, 0.0]]
    assert embedded["model_fingerprint"]
    chatted = _run(service.invoke_model(USER_ID, "model-chat", service.OP_CHAT, {"system": "", "history": []}, None))
    assert chatted["outputs"]["text"] == "answer"
    assert chatted["usage"]["total_tokens"] == 0
    STORE.models["model-foreign"] = _Model("model-foreign", "tenant-9", 1 << 1)
    with pytest.raises(service.GatewayError) as caught:
        _run(service.invoke_model(USER_ID, "model-foreign", service.OP_EMBED_QUERY, {"text": "q"}, None))
    assert caught.value.code == 108


def test_routes_require_the_user_header_and_stamp_the_version(gateway):
    service, routes, quart = gateway
    quart.request.headers = {service.SERVICE_KEY_HEADER: SERVICE_KEY}
    quart.request._body = {"kb_id": "kb1"}
    failed = _run(routes.documents_list())
    assert failed[1] == 400
    quart.request.headers = {service.SERVICE_KEY_HEADER: SERVICE_KEY, service.USER_HEADER: USER_ID}
    quart.request._body = {"kb_id": "kb1", "page_size": 2}
    body, status = _run(routes.documents_list())
    assert status == 200
    assert body.headers["X-Gateway-Version"] == "1"
    payload = body.get_json()
    assert payload["code"] == 0
    assert payload["data"]["next_cursor"] == "doc-b"
    assert [doc["id"] for doc in payload["data"]["documents"]] == ["doc-a", "doc-b"]


def test_session_reports_tenants_and_language(gateway):
    _service, routes, _quart = gateway
    body, status = _run(routes.session())
    assert status == 200
    assert body.get_json()["data"]["tenant_ids"] == ["tenant-1", USER_ID]


def test_password_session_requires_a_service_key(gateway):
    _service, routes, quart = gateway
    quart.request._body = {"email": "ada@example.org", "password": "ciphertext"}
    assert _run(routes.password_session())[1] == 403


def test_password_session_reads_identity_without_rotating_the_ragflow_token(gateway, monkeypatch):
    service, routes, quart = gateway
    user = SimpleNamespace(id=USER_ID, language="zh", nickname="Ada", is_active="1", access_token="current-token")

    def query_user(email, password):
        assert (email, password) == ("ada@example.org", "encoded-password")
        return user

    monkeypatch.setattr(service.UserService, "query_user", query_user)
    quart.request.headers = {service.SERVICE_KEY_HEADER: SERVICE_KEY, service.USER_HEADER: OTHER_USER}
    quart.request._body = {"email": "ada@example.org", "password": "ciphertext"}
    body, status = _run(routes.password_session())
    assert status == 200
    assert body.get_json()["data"] == {"user_id": USER_ID, "tenant_ids": ["tenant-1", USER_ID], "nickname": "Ada", "lang": "zh"}
    assert body.headers == {"X-Gateway-Version": "1"}
    assert user.access_token == "current-token"


@pytest.mark.parametrize("user", [None, SimpleNamespace(is_active="0")])
def test_password_session_rejects_invalid_credentials_and_disabled_accounts(gateway, monkeypatch, user):
    service, routes, quart = gateway
    monkeypatch.setattr(service.UserService, "query_user", lambda *_args: user)
    quart.request.headers = {service.SERVICE_KEY_HEADER: SERVICE_KEY}
    quart.request._body = {"email": "ada@example.org", "password": "ciphertext"}
    body, status = _run(routes.password_session())
    assert status == 401
    assert body.get_json()["data"] is None


def test_asset_checks_access_and_missing_model_is_not_found(gateway):
    service, _routes, _quart = gateway
    STORE.chunks["chk-1"]["img_id"] = "kb1-object"
    data, content_type = service.get_asset(USER_ID, "kb1-object")
    assert content_type == "image/png"
    assert data.startswith(b"\x89PNG")
    with pytest.raises(service.GatewayError) as denied:
        service.get_asset(USER_ID, "kbforeign-object")
    assert denied.value.code == 108
    with pytest.raises(service.GatewayError) as missing:
        _run(service.invoke_model(USER_ID, "missing", service.OP_CHAT, {}, None))
    assert missing.value.code == 404


def test_shared_asset_bucket_requires_a_visible_chunk_reference(gateway, monkeypatch):
    service, _, _ = gateway
    STORE.chunks["chk-1"]["img_id"] = "imagetemps-image"
    reads = []
    monkeypatch.setattr(service.settings.STORAGE_IMPL, "get", lambda bucket, key: reads.append((bucket, key)) or b"image")
    assert service.get_asset(USER_ID, "imagetemps-image")[0] == b"image"
    assert reads == [("imagetemps", "image")]
    with pytest.raises(service.GatewayError) as denied:
        service.get_asset(OTHER_USER, "imagetemps-image")
    assert denied.value.code == 108
    assert len(reads) == 1


def test_unknown_asset_bucket_is_denied_before_object_storage(gateway, monkeypatch):
    service, _routes, _quart = gateway
    def forbidden(*args):
        raise AssertionError("Object storage must not be accessed")
    monkeypatch.setattr(service.settings.STORAGE_IMPL, "get", forbidden)
    with pytest.raises(service.GatewayError) as denied:
        service.get_asset(USER_ID, "unknown-object")
    assert denied.value.code == 108


def test_dense_search_validates_every_knowledge_base_dimension(gateway, monkeypatch):
    service, _routes, _quart = gateway
    kb1, kb2 = _KB("kb1"), _KB("kb2")
    monkeypatch.setattr(service, "_require_kb", lambda kb_id, user_id: kb1 if kb_id == "kb1" else kb2)
    async def dimension(kb):
        return 4 if kb.id == "kb1" else 8
    monkeypatch.setattr(service, "_vector_dim", dimension)
    with pytest.raises(service.GatewayError, match="dimension"):
        _run(service.search_dense(USER_ID, ["kb1", "kb2"], {"vector": [1, 0, 0, 0]}, 5, None, 0))
