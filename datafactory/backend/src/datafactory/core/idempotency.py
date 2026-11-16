"""Stable hashing of creation requests and opaque idempotency keys."""

import hashlib
import json


def request_hash(body: dict) -> str:
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
