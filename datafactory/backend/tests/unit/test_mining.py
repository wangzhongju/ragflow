"""Hard negatives, leakage-safe splits and the release gates."""

import pytest

from datafactory.engine.mining import Candidate, check_gates, mine_negatives, split_rows


def _candidate(chunk_id: str, score: float, rank: int, **extra) -> Candidate:
    return Candidate(chunk_id=chunk_id, score=score, rank=rank, **extra)


def test_a_positive_its_parent_and_its_child_are_never_negatives():
    candidates = [
        _candidate("pos", 0.99, 1, parent_chunk_id="parent"),
        _candidate("parent", 0.4, 5),
        _candidate("child", 0.3, 6, parent_chunk_id="pos"),
        _candidate("ok", 0.2, 10),
    ]
    mined = mine_negatives(candidates, {"pos"}, positive_score=0.99, positive_signatures=[], n=7)
    kept = {candidate.chunk_id for candidate in mined.negatives}
    assert kept == {"ok"}


def test_a_near_duplicate_of_a_positive_is_excluded():
    signature = [1, 2, 3, 4]
    candidates = [
        _candidate("dup", 0.3, 8, minhash=signature),
        _candidate("other", 0.2, 9, minhash=[9, 9, 9, 9]),
    ]
    mined = mine_negatives(candidates, set(), 0.9, [signature])
    assert [candidate.chunk_id for candidate in mined.negatives] == ["other"]


def test_positive_aware_mining_drops_candidates_too_close_to_the_positive():
    candidates = [_candidate("close", 0.96, 4), _candidate("far", 0.4, 20)]
    mined = mine_negatives(candidates, set(), positive_score=1.0, positive_signatures=[], max_ratio_to_pos=0.95)
    assert [candidate.chunk_id for candidate in mined.negatives] == ["far"]


def test_a_high_teacher_score_marks_a_false_negative_instead_of_a_negative():
    candidates = [_candidate("suspect", 0.3, 12, teacher_score=0.91), _candidate("clean", 0.2, 13, teacher_score=0.1)]
    mined = mine_negatives(candidates, set(), 0.9, [])
    assert [candidate.chunk_id for candidate in mined.false_negative_suspects] == ["suspect"]
    assert [candidate.chunk_id for candidate in mined.negatives] == ["clean"]


def test_either_relative_or_absolute_teacher_threshold_diverts_to_review():
    relative = mine_negatives([_candidate("r", 0.1, 3, teacher_score=0.46)], set(), 0.5, [])
    absolute = mine_negatives([_candidate("a", 0.1, 3, teacher_score=0.81)], set(), 1.0, [])
    assert relative.false_negative_suspects[0].chunk_id == "r"
    assert absolute.false_negative_suspects[0].chunk_id == "a"
    assert not relative.negatives and not absolute.negatives


def test_parent_exclusion_does_not_require_positive_in_retrieval_results():
    result = mine_negatives([_candidate("parent", 0.1, 3)], {"positive"}, 1.0, [], positive_parent_ids={"parent"})
    assert result.negatives == []


def test_containment_excludes_candidates_even_when_minhash_is_not_similar():
    result = mine_negatives(
        [_candidate("part", 0.1, 3, text="turn valve")],
        {"positive"},
        1.0,
        [],
        positive_texts=["first turn valve then replace filter"],
    )
    assert result.negatives == []


def test_a_family_never_crosses_a_split():
    rows = [{"row_key": f"r{i}", "group_key": "family_1"} for i in range(6)]
    rows += [{"row_key": f"s{i}", "group_key": "family_2"} for i in range(6)]
    assigned = split_rows(rows, {"train": 0.5, "test": 0.5}, seed=42)
    by_family: dict[str, set[str]] = {}
    for row in assigned:
        by_family.setdefault(row["group_key"], set()).add(row["split"])
    assert all(len(splits) == 1 for splits in by_family.values())


def test_the_same_group_always_lands_in_the_same_split():
    rows = [{"row_key": "r", "group_key": "family_7"}]
    first = split_rows(rows, {"train": 0.8, "val": 0.1, "test": 0.1}, 7)
    second = split_rows(rows, {"train": 0.8, "val": 0.1, "test": 0.1}, 7)
    assert first[0]["split"] == second[0]["split"]


def test_transitive_shared_positive_and_query_links_do_not_leak():
    rows = [
        {"row_key": "a", "group_key": "f1", "positives": ["p1"], "query": "alpha beta gamma delta epsilon"},
        {"row_key": "b", "group_key": "f2", "positives": ["p1", "p2"], "query": "unrelated"},
        {"row_key": "c", "group_key": "f3", "positives": ["p3"], "query": "alpha beta gamma delta epsilon zeta"},
        {"row_key": "d", "group_key": "f4", "positives": ["p2"], "query": "different"},
    ]
    assigned = split_rows(rows, {"train": 0.8, "test": 0.2}, 42)
    reverse = split_rows(list(reversed(rows)), {"train": 0.8, "test": 0.2}, 42)
    assert len({row["split"] for row in assigned}) == 1
    assert {row["row_key"]: row["split_group"] for row in assigned} == {
        row["row_key"]: row["split_group"] for row in reverse
    }
    assigned[-1]["split"] = "test" if assigned[0]["split"] == "train" else "train"
    assert not next(gate for gate in check_gates(assigned, "ready") if gate.name == "cross_split_leakage").passed


def _sample(**extra) -> dict:
    base = {
        "split": "train",
        "positives": ["p1"],
        "negatives": ["n1"],
        "judge": {"overall": 8},
        "false_negative_suspects": [],
    }
    base.update(extra)
    return base


def test_leakage_blocks_a_release():
    samples = [_sample(positives=["p1"], split="train"), _sample(positives=["p1"], split="test")]
    gates = {gate.name: gate for gate in check_gates(samples, "ready")}
    assert gates["cross_split_leakage"].passed is False
    assert gates["cross_split_leakage"].level == "blocker"


def test_a_clean_set_passes_every_blocker():
    samples = [_sample(split="train"), _sample(split="test", positives=["p2"])]
    blockers = [gate for gate in check_gates(samples, "ready") if gate.level == "blocker"]
    assert all(gate.passed for gate in blockers)


def test_unresolved_false_negatives_block():
    samples = [_sample(false_negative_suspects=["c9"])]
    gates = {gate.name: gate for gate in check_gates(samples, "ready")}
    assert gates["false_negatives"].passed is False


def test_a_stale_snapshot_warns_but_does_not_block():
    gates = {gate.name: gate for gate in check_gates([_sample()], "stale")}
    assert gates["snapshot_fresh"].passed is False
    assert gates["snapshot_fresh"].level == "warning"


@pytest.mark.parametrize("judge", [{}, None, "8", {"overall": float("nan")}, {"overall": "8"}, {"overall": 11}])
def test_invalid_or_missing_judgments_cannot_pass_release_gates(judge):
    gate = next(item for item in check_gates([_sample(judge=judge)], "ready") if item.name == "judge_score")
    assert not gate.passed
