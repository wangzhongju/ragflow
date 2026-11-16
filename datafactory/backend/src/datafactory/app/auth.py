"""Who the current request acts as.

The browser signs in through RAGFlow. The platform resolves that login once,
through the gateway's ``GET /session``, and keeps the resulting user id in a
signed cookie of its own. Workers never see the cookie: they call the gateway
with the service key and the user id stored on the run.
"""

import hashlib
import hmac
import time

from fastapi import Request

from datafactory.core.errors import Unauthorized

_COOKIE = "df_session"
SESSION_TTL = 3600


def current_user(request: Request) -> str:
    """The user id for this request, or 401 when there is no session."""
    user_id = request.scope.get("df_user_id", "")
    if not user_id:
        raise Unauthorized("Sign in through RAGFlow first.")
    return user_id


def session_cookie(user_id: str, secret: str) -> tuple[str, str]:
    """Sign the identity and an absolute expiry; browser expiry alone is insufficient."""
    payload = f"{user_id}.{int(time.time()) + SESSION_TTL}"
    return _COOKIE, f"{payload}.{_sign(payload, secret)}"


def read_cookie(request: Request, secret: str) -> str:
    """The user id from a cookie signed with ``secret``, or an empty string.

    A missing cookie, a cookie without a signature, and a cookie signed with
    another secret all read as no session.
    """
    raw = request.cookies.get(_COOKIE, "")
    payload, separator, signature = raw.rpartition(".")
    if not separator or not signature.isascii() or not hmac.compare_digest(signature, _sign(payload, secret)):
        return ""
    user_id, _, expires = payload.rpartition(".")
    if not expires.isdigit() or int(expires) <= time.time():
        return ""
    return user_id


def _sign(user_id: str, secret: str) -> str:
    return hmac.new(secret.encode(), user_id.encode(), hashlib.sha256).hexdigest()
