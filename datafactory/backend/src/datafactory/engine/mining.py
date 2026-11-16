"""Hard-negative selection.

A candidate becomes a negative only when it is far enough below the positive and
not related to one. The default strategy is positive-aware: a candidate must
score under the positive score times ``max_ratio_to_pos``.
"""

import hashlib
import math
from dataclasses import dataclass, field

from datafactory.domain.fingerprint import jaccard, normalize

_NEAR = 0.8


@dataclass
class Candidate:
    """One retrieved chunk with the scores that decide its fate."""

    chunk_id: str
    score: float
    rank: int
    minhash: list[int] = field(default_factory=list)
    parent_chunk_id: str = ""
    teacher_score: float | None = None
    text: str = ""


@dataclass
class Mined:
    """The negatives kept for one query, and the candidates rejected as false negatives."""

    negatives: list[Candidate]
    false_negative_suspects: list[Candidate]


def mine_negatives(
    candidates: list[Candidate],
    positive_ids: set[str],
    positive_score: float,
    positive_signatures: list[list[int]],
    strategy: str = "topk_percpos",
    n: int = 7,
    rank_range: tuple[int, int] = (3, 60),
    max_ratio_to_pos: float = 0.95,
    margin: float = 0.1,
    teacher_band: tuple[float, float] = (0.2, 0.6),
    teacher_threshold: float = 0.8,
    positive_parent_ids: set[str] | None = None,
    positive_texts: list[str] | None = None,
) -> Mined:
    """Select up to ``n`` negatives and list the candidates that look like missed positives.

    Related chunks are removed before the strategy runs, so no strategy can
    select a positive, its parent or child, or a near duplicate of a positive.
    """
    related = _related(positive_ids, candidates) | (positive_parent_ids or set())
    texts = [normalize(text) for text in positive_texts or [] if normalize(text)]
    eligible = [
        candidate
        for candidate in candidates
        if candidate.chunk_id not in related
        and not _near(candidate, positive_signatures)
        and not any(
            normalize(candidate.text) and (normalize(candidate.text) in text or text in normalize(candidate.text))
            for text in texts
        )
    ]
    suspects = [
        candidate
        for candidate in eligible
        if candidate.teacher_score is not None
        and candidate.teacher_score >= min(teacher_threshold, positive_score * 0.9)
    ]
    suspect_ids = {candidate.chunk_id for candidate in suspects}
    pool = [candidate for candidate in eligible if candidate.chunk_id not in suspect_ids]
    chosen = _strategy(strategy, pool, positive_score, rank_range, max_ratio_to_pos, margin, teacher_band)[:n]
    return Mined(negatives=chosen, false_negative_suspects=suspects)


def _related(positive_ids: set[str], candidates: list[Candidate]) -> set[str]:
    """Positives, their parents and their children.

    The parent link is recorded on the child, so both directions are checked:
    a candidate whose parent is a positive, and the candidate a positive names
    as its parent.
    """
    parents = {candidate.chunk_id: candidate.parent_chunk_id for candidate in candidates}
    children_of: dict[str, list[str]] = {}
    for candidate in candidates:
        if candidate.parent_chunk_id:
            children_of.setdefault(candidate.parent_chunk_id, []).append(candidate.chunk_id)
    blocked = set(positive_ids)
    for positive in positive_ids:
        if parents.get(positive):
            blocked.add(parents[positive])
        blocked.update(children_of.get(positive, []))
    for candidate in candidates:
        if candidate.parent_chunk_id in positive_ids:
            blocked.add(candidate.chunk_id)
    return blocked


def _near(candidate: Candidate, positives: list[list[int]]) -> bool:
    return any(jaccard(candidate.minhash, signature) >= _NEAR for signature in positives)


def _strategy(strategy, pool, positive_score, rank_range, max_ratio, margin, teacher_band) -> list[Candidate]:
    if strategy == "topk_range":
        low, high = rank_range
        return [candidate for candidate in pool if low <= candidate.rank <= high]
    if strategy == "topk_margin":
        return [candidate for candidate in pool if candidate.score < positive_score - margin]
    if strategy == "teacher_band":
        low, high = teacher_band
        return [
            candidate
            for candidate in pool
            if candidate.teacher_score is not None and low <= candidate.teacher_score <= high
        ]
    if strategy == "topk_percpos":
        return [candidate for candidate in pool if candidate.score < positive_score * max_ratio]
    raise ValueError(f"Unknown mining strategy {strategy}.")


def split_rows(rows: list[dict], ratios: dict[str, float], seed: int) -> list[dict]:
    """Assign each row a split from its group key, so a group never breaks apart.

    The group key is the document family. Rows sharing a family land in the same
    split, which is what keeps a document out of both train and test.
    """
    if not ratios or any(value < 0 for value in ratios.values()) or abs(sum(ratios.values()) - 1) > 1e-9:
        raise ValueError("Split ratios must be nonnegative and sum to one.")
    names = sorted(ratios)
    bounds = []
    covered = 0.0
    for name in names:
        covered += ratios[name]
        bounds.append((covered, name))
    assigned = []
    for row in rows:
        point = _point(row["group_key"], seed)
        split = names[-1]
        for bound, name in bounds:
            if point <= bound:
                split = name
                break
        assigned.append({**row, "split": split})
    return assigned


def _point(group_key: str, seed: int) -> float:
    digest = hashlib.sha256(f"{seed}|{group_key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


@dataclass
class GateResult:
    """One release gate. A blocker stops the release; a warning needs confirmation."""

    name: str
    level: str
    passed: bool
    detail: str


def check_gates(samples: list[dict], snapshot_status: str, min_negatives: int = 1) -> list[GateResult]:
    """The embedding release gates. Thresholds are the defaults from the design.

    ``samples`` carry ``split``, ``positives``, ``negatives``, ``judge`` and
    ``false_negative_suspects``. Leakage is measured from the data, not from a
    stored flag, so a hand-edited split cannot hide it.
    """
    return [
        _leakage(samples),
        _counts(samples, min_negatives),
        _false_negatives(samples),
        _judge(samples),
        _staleness(snapshot_status),
    ]


def _leakage(samples: list[dict]) -> GateResult:
    seen: dict[str, str] = {}
    leaked = 0
    for sample in samples:
        for positive in sample.get("positives", []):
            earlier = seen.get(positive)
            if earlier and earlier != sample["split"]:
                leaked += 1
            seen.setdefault(positive, sample["split"])
    return GateResult(
        "cross_split_leakage", "blocker", leaked == 0, f"{leaked} positives appear in more than one split."
    )


def _counts(samples: list[dict], min_negatives: int) -> GateResult:
    short = [
        sample
        for sample in samples
        if len(sample.get("positives", [])) < 1
        or len(sample.get("negatives", [])) < min_negatives
        or set(sample.get("positives", [])) & set(sample.get("negatives", []))
    ]
    return GateResult(
        "example_counts", "blocker", not short, f"{len(short)} samples have too few positives or negatives."
    )


def _false_negatives(samples: list[dict]) -> GateResult:
    pending = sum(len(sample.get("false_negative_suspects", [])) for sample in samples)
    return GateResult(
        "false_negatives", "blocker", pending == 0, f"{pending} suspected false negatives are unresolved."
    )


def _judge(samples: list[dict]) -> GateResult:
    low = []
    for sample in samples:
        judge = sample.get("judge")
        score = judge.get("overall") if isinstance(judge, dict) else None
        if (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(score)
            or not 7 <= score <= 10
        ):
            low.append(sample)
    return GateResult("judge_score", "blocker", not low, f"{len(low)} samples scored below 7.")


def _staleness(status: str) -> GateResult:
    return GateResult("snapshot_fresh", "warning", status != "stale", f"Snapshot status is {status}.")
