"""HTTP client for the Corpus Gateway.

This is the only code that speaks to RAGFlow. It sends the service key and the
user it acts for, checks the contract version on the first response, and turns
the gateway's ``{code, data, message}`` envelope into typed records or a
``GatewayUnavailable`` error.
"""

import json
from collections.abc import AsyncIterator, Mapping

import httpx

from datafactory.core.errors import GatewayUnavailable, GatewayVersionMismatch
from datafactory.core.settings import GatewaySettings
from datafactory.gateway.dto import (
    Chunk,
    Dataset,
    DenseSearch,
    DocumentPage,
    Invocation,
    Model,
    Session,
)

_SERVICE_KEY = "X-DF-Service-Key"
_USER = "X-DF-User-Id"
_REQUEST = "X-DF-Request-Id"
_VERSION = "X-Gateway-Version"


class GatewayClient:
    """One client bound to one user. A new user means a new client."""

    def __init__(
        self,
        settings: GatewaySettings,
        user_id: str,
        request_id: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._user_id = user_id
        self._request_id = request_id
        self._transport = transport
        self._version_checked = False

    def _http(self, timeout: float | None) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    async def session_from_token(self, authorization: str) -> Session:
        """Resolve a browser user's JWT into the user the platform acts for.

        This is the one call that sends the user's own token instead of the
        service key, matching ``GET /gateway/session``.
        """
        async with self._http(self._settings.gateway_timeout_s) as http:
            response = await http.get(
                self._url("/gateway/session"),
                headers={"Authorization": authorization, _REQUEST: self._request_id},
            )
        self._check_version(response)
        return Session.model_validate(self._data(response))

    async def list_datasets(self) -> list[Dataset]:
        """Knowledge bases the bound user can read."""
        return [Dataset.model_validate(row) for row in await self._get("/gateway/datasets")]

    async def list_documents(self, kb_id: str, cursor: str | None = None, page_size: int = 200) -> DocumentPage:
        """One page of documents. Pass the returned cursor back for the next page."""
        body = {"kb_id": kb_id, "page_size": page_size}
        if cursor:
            body["page_cursor"] = cursor
        return DocumentPage.model_validate(await self._post("/gateway/documents:list", body))

    async def scan_chunks(
        self,
        kb_id: str,
        doc_ids: list[str],
        include_vector: bool = False,
        include_unavailable: bool = False,
    ) -> AsyncIterator[Chunk]:
        """Yield every chunk of the documents, checking each document's EOF line.

        The gateway ends each document with ``{"_eof": true, "count": n}``. A
        stream that stops early, or whose count disagrees with the rows seen,
        raises rather than silently returning a partial corpus.
        """
        payload = {
            "kb_id": kb_id,
            "doc_ids": doc_ids,
            "include_vector": include_vector,
            "include_unavailable": include_unavailable,
        }
        async with self._http(self._settings.gateway_timeout_s) as http:
            async with http.stream(
                "POST", self._url("/gateway/chunks:scan"), json=payload, headers=self._headers()
            ) as response:
                self._check_version(response)
                if response.status_code >= 400:
                    raise GatewayUnavailable(f"Gateway chunks:scan failed with HTTP {response.status_code}.")
                seen: dict[str, int] = dict.fromkeys(doc_ids, 0)
                chunk_ids: set[str] = set()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    row = json.loads(line)
                    if row.get("doc_id") not in seen:
                        raise GatewayUnavailable("Chunk stream contains an unrequested document.")
                    if row.get("_eof"):
                        doc_id = row["doc_id"]
                        if seen.get(doc_id, 0) != row["count"]:
                            raise GatewayUnavailable(
                                f"Chunk stream for {doc_id} ended after {seen.get(doc_id, 0)} rows "
                                f"but reported {row['count']}."
                            )
                        seen[doc_id] = -1
                        continue
                    chunk = Chunk.model_validate(row)
                    if chunk.kb_id != kb_id or chunk.chunk_id in chunk_ids:
                        raise GatewayUnavailable("Chunk stream contains a foreign or duplicate chunk.")
                    chunk_ids.add(chunk.chunk_id)
                    if seen.get(chunk.doc_id) == -1:
                        raise GatewayUnavailable(f"Chunk stream for {chunk.doc_id} continued after its EOF line.")
                    seen[chunk.doc_id] = seen.get(chunk.doc_id, 0) + 1
                    yield chunk
        unfinished = [doc_id for doc_id, count in seen.items() if count != -1]
        if unfinished:
            raise GatewayUnavailable(f"Chunk stream ended before EOF for: {', '.join(unfinished)}.")

    async def list_models(self, types: list[str] | None = None) -> list[Model]:
        """Models the bound user may call, optionally restricted to some types."""
        params = {"types": ",".join(types)} if types else None
        return [Model.model_validate(row) for row in await self._get("/gateway/models", params)]

    async def invoke(self, model_id: str, op: str, inputs: dict, gen_conf: dict | None = None) -> Invocation:
        """Run one model operation. Prompt assembly stays with the caller."""
        body = {"model_id": model_id, "op": op, "inputs": inputs, "gen_conf": gen_conf or {}}
        return Invocation.model_validate(await self._post("/gateway/models:invoke", body))

    async def search_dense(
        self,
        kb_ids: list[str],
        query: dict,
        top_k: int,
        filters: dict | None = None,
        min_score: float = 0.0,
    ) -> DenseSearch:
        """Dense retrieval over the stored vectors of the given knowledge bases."""
        body = {"kb_ids": kb_ids, "query": query, "top_k": top_k, "filters": filters, "min_score": min_score}
        return DenseSearch.model_validate(await self._post("/gateway/search:dense", body))

    async def get_asset(self, img_id: str) -> tuple[bytes, str]:
        """The bytes and content type of one RAGFlow image. The body is not JSON."""
        async with self._http(self._settings.gateway_timeout_s) as http:
            response = await http.get(self._url(f"/gateway/assets/{img_id}"), headers=self._headers())
        self._check_version(response)
        if response.status_code >= 400:
            raise GatewayUnavailable(
                f"Gateway asset {img_id} failed with HTTP {response.status_code}.", gateway_code=response.status_code
            )
        return response.content, response.headers.get("content-type", "application/octet-stream")

    def _url(self, path: str) -> str:
        return self._settings.gateway_base_url.rstrip("/") + path

    def _headers(self) -> dict[str, str]:
        return {
            _SERVICE_KEY: self._settings.gateway_service_key,
            _USER: self._user_id,
            _REQUEST: self._request_id,
        }

    async def _get(self, path: str, params: Mapping[str, str] | None = None):
        async with self._http(self._settings.gateway_timeout_s) as http:
            response = await http.get(self._url(path), headers=self._headers(), params=params)
        self._check_version(response)
        return self._data(response)

    async def _post(self, path: str, body: dict):
        async with self._http(self._settings.gateway_timeout_s) as http:
            response = await http.post(self._url(path), headers=self._headers(), json=body)
        self._check_version(response)
        return self._data(response)

    def _check_version(self, response: httpx.Response) -> None:
        """Refuse to continue when the gateway speaks another contract version.

        Checked once per client. A response without the header (the gateway is
        disabled and answers 404) is reported as unavailable instead.
        """
        if self._version_checked:
            return
        found = response.headers.get(_VERSION)
        if found is None:
            return
        if found != self._settings.gateway_version:
            raise GatewayVersionMismatch(
                f"Gateway speaks contract version {found}, this build expects {self._settings.gateway_version}."
            )
        self._version_checked = True

    @staticmethod
    def _data(response: httpx.Response):
        """Unwrap one JSON envelope, raising with the gateway's own message on failure."""
        if response.status_code == 429:
            raise GatewayUnavailable("Gateway is at its model-call limit.", gateway_code=429)
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise GatewayUnavailable(f"Gateway returned a non-JSON response (HTTP {response.status_code}).") from exc
        code = payload.get("code", 0)
        if response.status_code >= 400 or code:
            raise GatewayUnavailable(
                payload.get("message") or f"Gateway error {code}.", gateway_code=code or response.status_code
            )
        return payload.get("data")
