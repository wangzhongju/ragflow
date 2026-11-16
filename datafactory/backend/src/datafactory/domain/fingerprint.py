"""Normalization, hashing and near-duplicate signatures for frozen segments.

The hash covers the content only, so two chunks with the same text and the same
images freeze as one content identity even when their positions differ.
"""

import hashlib
import re

from datasketch import MinHash

from datafactory.domain.content import ContentPart, Modality

_PERMUTATIONS = 64
_MINHASH_SEED = 42
_TOKEN = re.compile(r"\w+", re.UNICODE)


def normalize(text: str) -> str:
    """Collapse whitespace so trivial formatting differences share a hash."""
    return " ".join(text.split())


def part_fingerprint(part: ContentPart) -> str:
    """The canonical string of one part, used by the segment hash."""
    if part.type == "text":
        return "text:" + normalize(part.text or "")
    if part.type == "table":
        return "table:" + normalize(part.text or "") + "|" + (part.html or "")
    return f"{part.type}:{part.asset_id or ''}"


def content_hash(parts: list[ContentPart]) -> str:
    """SHA-256 over the normalized parts, prefixed so the kind is obvious."""
    joined = "\n".join(part_fingerprint(part) for part in parts)
    return "sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()


def modality_of(parts: list[ContentPart]) -> Modality:
    """The modality of a part list. More than one kind is ``mixed``."""
    kinds = {(part.type if part.type != "json" else "text") for part in parts if part.type != "json"}
    if not kinds or kinds == {"text"}:
        return "text"
    if len(kinds) == 1:
        only = kinds.pop()
        return only if only in ("image", "audio", "video", "table") else "text"
    return "mixed"


def tokens_of(parts: list[ContentPart]) -> int:
    """A whitespace token count. Good enough for length gates, not for billing."""
    return sum(len(_TOKEN.findall(part.text or "")) for part in parts)


def minhash_of(parts: list[ContentPart]) -> list[int]:
    """A MinHash signature of the textual parts. Empty text gives an empty signature."""
    tokens = _TOKEN.findall(" ".join(part.text or "" for part in parts if part.type in ("text", "table")))
    if not tokens:
        return []
    signature = MinHash(num_perm=_PERMUTATIONS, seed=_MINHASH_SEED)
    for token in tokens:
        signature.update(token.lower().encode("utf-8"))
    return [int(value) for value in signature.hashvalues]


def jaccard(left: list[int], right: list[int]) -> float:
    """Estimated Jaccard similarity of two signatures. Mismatched lengths compare as 0."""
    if not left or not right or len(left) != len(right):
        return 0.0
    same = sum(1 for a, b in zip(left, right, strict=True) if a == b)
    return same / len(left)


def garbage_ratio(text: str) -> float:
    """Share of characters that are neither printable nor whitespace."""
    if not text:
        return 0.0
    bad = sum(1 for char in text if not char.isprintable() and not char.isspace())
    return bad / len(text)
