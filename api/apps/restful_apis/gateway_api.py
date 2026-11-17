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
"""Corpus Gateway routes, mounted at ``/api/v1/gateway``.

The blueprint is registered automatically because this module lives in
``restful_apis``. Every route is read-only apart from model invocation, which
only reads credentials and reports usage. Password verification does not issue
or update RAGFlow login tokens.

Authentication is two layers: the ``X-DF-Service-Key`` header must match
``DATAFACTORY_SERVICE_KEY`` (the whole blueprint answers 404 when that variable
is unset, so an unconfigured deployment exposes nothing), and ``X-DF-User-Id``
names the user the call acts for. ``GET /session`` takes the browser's RAGFlow
JWT instead. ``POST /session`` requires the service key and derives the user
identity from the submitted credentials.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os

from quart import Response, g, request

from api.apps import AUTH_JWT, login_required
from api.apps.services import gateway_service as gw
from api.utils.api_utils import get_json_result
from common.constants import RetCode

page_name = "gateway"
_logger = logging.getLogger(__name__)

_inflight = 0
_inflight_lock = asyncio.Lock()


def _disabled():
    return get_json_result(code=RetCode.NOT_FOUND, message="Not Found"), 404


def _service_key_ok() -> bool:
    expected = os.environ.get("DATAFACTORY_SERVICE_KEY", "").strip()
    if not expected:
        return False
    given = request.headers.get(gw.SERVICE_KEY_HEADER, "")
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def _user_id() -> str:
    user_id = request.headers.get(gw.USER_HEADER, "").strip()
    if not user_id:
        raise gw.GatewayError(RetCode.ARGUMENT_ERROR, f"{gw.USER_HEADER} header is required.")
    return user_id


def _versioned(response):
    body, status = response if isinstance(response, tuple) else (response, 200)
    body.headers["X-Gateway-Version"] = gw.GATEWAY_VERSION
    return body, status


async def _guard():
    """Return an error response when the gateway is disabled or the key is wrong."""
    if not gw.gateway_enabled():
        return _disabled()
    if not _service_key_ok():
        return get_json_result(code=RetCode.AUTHENTICATION_ERROR, message="Invalid service key."), 403
    return None


def _fail(exc: Exception):
    if isinstance(exc, gw.GatewayError):
        _logger.warning("gateway: %s", exc.message)
        return get_json_result(code=exc.code, message=exc.message), _http_status(exc.code)
    _logger.exception("gateway request failed")
    return get_json_result(code=RetCode.EXCEPTION_ERROR, message="Gateway request failed."), 500


def _http_status(code: int) -> int:
    return {
        RetCode.ARGUMENT_ERROR: 400,
        RetCode.DATA_ERROR: 400,
        RetCode.PERMISSION_ERROR: 403,
        RetCode.AUTHENTICATION_ERROR: 403,
        RetCode.UNAUTHORIZED: 401,
        RetCode.NOT_FOUND: 404,
    }.get(code, 200)


async def _body() -> dict:
    data = await request.get_json(force=True, silent=True)
    if data is None:
        raise gw.GatewayError(RetCode.ARGUMENT_ERROR, "Request body must be JSON.")
    if not isinstance(data, dict):
        raise gw.GatewayError(RetCode.ARGUMENT_ERROR, "Request body must be a JSON object.")
    return data


def _session_response(user):
    data = {
        "user_id": user.id,
        "tenant_ids": gw.joined_tenant_ids(user.id),
        "nickname": user.nickname,
        "lang": user.language,
    }
    return _versioned(get_json_result(data=data))


@manager.route("/session", methods=["GET"])  # noqa: F821
@login_required(auth_types=[AUTH_JWT])
async def session():
    if not gw.gateway_enabled():
        return _disabled()
    return _session_response(g.user)


@manager.route("/session", methods=["POST"])  # noqa: F821
async def password_session():
    blocked = await _guard()
    if blocked:
        return blocked
    try:
        body = await _body()
        email, password = body.get("email"), body.get("password")
        if not isinstance(email, str) or not email or not isinstance(password, str) or not password:
            raise gw.GatewayError(RetCode.ARGUMENT_ERROR, "Email and encrypted password are required.")
        user = await asyncio.to_thread(gw.authenticate_user, email, password)
        return _session_response(user)
    except gw.GatewayError as exc:
        return _fail(exc)


@manager.route("/datasets", methods=["GET"])  # noqa: F821
async def datasets():
    blocked = await _guard()
    if blocked:
        return blocked
    try:
        return _versioned(get_json_result(data=gw.list_datasets(_user_id())))
    except gw.GatewayError as exc:
        return _fail(exc)


@manager.route("/documents:list", methods=["POST"])  # noqa: F821
async def documents_list():
    blocked = await _guard()
    if blocked:
        return blocked
    try:
        body = await _body()
        kb_id = body.get("kb_id", "")
        if not kb_id:
            raise gw.GatewayError(RetCode.ARGUMENT_ERROR, "kb_id is required.")
        page_size = min(1000, max(1, int(body.get("page_size", 200))))
        data = gw.list_documents(_user_id(), kb_id, body.get("doc_ids"), body.get("page_cursor"), page_size)
        return _versioned(get_json_result(data=data))
    except gw.GatewayError as exc:
        return _fail(exc)


@manager.route("/chunks:scan", methods=["POST"])  # noqa: F821
async def chunks_scan():
    """Stream every chunk of the requested documents as NDJSON.

    Each document ends with an EOF line carrying its chunk count, so a client
    can confirm the stream was complete. Documents over ``SCAN_BATCH_SIZE``
    chunks are paged internally; the client sees one continuous stream.
    """
    blocked = await _guard()
    if blocked:
        return blocked
    try:
        body = await _body()
        user_id = _user_id()
        kb_id = body.get("kb_id", "")
        doc_ids = body.get("doc_ids") or []
        if not kb_id or not doc_ids:
            raise gw.GatewayError(RetCode.ARGUMENT_ERROR, "kb_id and doc_ids are required.")
        fields = body.get("fields")
        include_vector = bool(body.get("include_vector", False))
        include_unavailable = bool(body.get("include_unavailable", False))
        kb = gw.document_ready(user_id, kb_id, doc_ids[0]) and _kb(kb_id)
        docs = [gw.document_ready(user_id, kb_id, doc_id) for doc_id in doc_ids]
    except gw.GatewayError as exc:
        return _fail(exc)

    async def generate():
        for doc in docs:
            count = 0
            offset = 0
            while True:
                batch = gw.scan_batch(kb.tenant_id, kb_id, doc.id, offset, fields)
                if include_vector and batch:
                    batch = await gw.attach_vectors(kb.tenant_id, kb_id, batch)
                for chunk in batch:
                    if not include_unavailable and chunk["available"] == 0:
                        continue
                    count += 1
                    yield json.dumps(chunk, ensure_ascii=False) + "\n"
                if len(batch) < gw.SCAN_BATCH_SIZE:
                    break
                offset += gw.SCAN_BATCH_SIZE
            yield json.dumps({"_eof": True, "doc_id": doc.id, "count": count}, ensure_ascii=False) + "\n"

    response = Response(generate(), mimetype="application/x-ndjson")
    response.headers["X-Gateway-Version"] = gw.GATEWAY_VERSION
    return response


def _kb(kb_id: str):
    from api.db.services.knowledgebase_service import KnowledgebaseService

    ok, kb = KnowledgebaseService.get_by_id(kb_id)
    if not ok:
        raise gw.GatewayError(RetCode.NOT_FOUND, f"Knowledge base {kb_id} not found.")
    return kb


@manager.route("/chunks:vectors", methods=["POST"])  # noqa: F821
async def chunks_vectors():
    blocked = await _guard()
    if blocked:
        return blocked
    try:
        body = await _body()
        return _versioned(get_json_result(data=await gw.fetch_vectors(_user_id(), body.get("kb_id", ""), body.get("chunk_ids") or [])))
    except gw.GatewayError as exc:
        return _fail(exc)


@manager.route("/search:dense", methods=["POST"])  # noqa: F821
async def search_dense():
    blocked = await _guard()
    if blocked:
        return blocked
    try:
        body = await _body()
        data = await gw.search_dense(
            _user_id(),
            body.get("kb_ids") or [],
            body.get("query") or {},
            int(body.get("top_k", 100)),
            body.get("filters"),
            float(body.get("min_score", 0.0)),
        )
        return _versioned(get_json_result(data=data))
    except gw.GatewayError as exc:
        return _fail(exc)


@manager.route("/search:production", methods=["POST"])  # noqa: F821
async def search_production():
    blocked = await _guard()
    if blocked:
        return blocked
    try:
        body = await _body()
        data = await gw.search_production(
            _user_id(),
            body.get("kb_ids") or [],
            body.get("question", ""),
            int(body.get("top_k", 30)),
            body.get("doc_ids"),
            bool(body.get("use_rerank", False)),
            body.get("must_not"),
        )
        return _versioned(get_json_result(data=data))
    except gw.GatewayError as exc:
        return _fail(exc)


@manager.route("/assets/<img_id>", methods=["GET"])  # noqa: F821
async def asset(img_id: str):
    blocked = await _guard()
    if blocked:
        return blocked
    try:
        data, content_type = gw.get_asset(_user_id(), img_id)
    except gw.GatewayError as exc:
        return _fail(exc)
    response = Response(data, mimetype=content_type)
    response.headers["ETag"] = hashlib.sha256(data).hexdigest()
    response.headers["X-Gateway-Version"] = gw.GATEWAY_VERSION
    return response


@manager.route("/models", methods=["GET"])  # noqa: F821
async def models():
    blocked = await _guard()
    if blocked:
        return blocked
    try:
        types = [item for item in request.args.get("types", "").split(",") if item]
        return _versioned(get_json_result(data=gw.list_models(_user_id(), types or None)))
    except gw.GatewayError as exc:
        return _fail(exc)


@manager.route("/models:invoke", methods=["POST"])  # noqa: F821
async def models_invoke():
    blocked = await _guard()
    if blocked:
        return blocked
    acquired = await _acquire_inflight()
    if not acquired:
        body = get_json_result(code=RetCode.SERVER_ERROR, message="Too many model calls in flight.")
        body.status_code = 429
        return body
    try:
        body = await _body()
        data = await gw.invoke_model(
            _user_id(),
            body.get("model_id", ""),
            body.get("op", ""),
            body.get("inputs") or {},
            body.get("gen_conf"),
        )
        return _versioned(get_json_result(data=data))
    except gw.GatewayError as exc:
        return _fail(exc)
    finally:
        await _release_inflight()


async def _acquire_inflight() -> bool:
    global _inflight
    async with _inflight_lock:
        if _inflight >= gw.max_inflight():
            return False
        _inflight += 1
        return True


async def _release_inflight() -> None:
    global _inflight
    async with _inflight_lock:
        _inflight = max(0, _inflight - 1)
