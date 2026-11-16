"""A scripted Corpus Gateway for tests that drive the client through HTTP.

Unit tests build their own ``httpx.MockTransport`` inline. This module is the
shared shape later suites reuse: one handler map from path to envelope.
"""

import httpx


def envelope(data, code: int = 0, message: str = "") -> dict:
    """One gateway response body."""
    return {"code": code, "data": data, "message": message}


def transport(routes: dict[str, dict]) -> httpx.MockTransport:
    """A transport answering each path with the envelope registered for it."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = routes.get(request.url.path)
        if body is None:
            return httpx.Response(404, json=envelope(None, code=404, message=f"no stub for {request.url.path}"))
        return httpx.Response(200, json=body, headers={"X-Gateway-Version": "1"})

    return httpx.MockTransport(handler)
