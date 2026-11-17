"""Golden exports. A fixed release must produce fixed bytes for every adapter."""

import json
from pathlib import Path

import pytest

from datafactory.adapters import (
    AdapterError,
    ReleaseCorpus,
    ReleaseSample,
    export_beir,
    export_canonical,
    export_flagembedding,
    export_sentence_transformers,
)

_CORPUS = ReleaseCorpus(
    segments={"seg_1": "Notice is required thirty days before revocation.", "seg_2": "Sourdough needs wild yeast."},
    modalities={"seg_1": "text", "seg_2": "text"},
)

_SAMPLES = [
    ReleaseSample("q1", "What notice does revocation require?", "train", ["seg_1"], ["seg_2"], [0.9], [0.2]),
    ReleaseSample("q2", "How is sourdough started?", "test", ["seg_2"], ["seg_1"], [0.8], [0.1]),
]


def test_canonical_keeps_every_split_and_modality():
    image = ReleaseSample("q3", "Which figure?", "train", ["seg_3"], [], modality="image")
    corpus = ReleaseCorpus(
        segments={**_CORPUS.segments, "seg_3": ""}, modalities={**_CORPUS.modalities, "seg_3": "image"}
    )
    result = export_canonical([*_SAMPLES, image], corpus)
    assert '"query_id": "q3"' in result.files["samples/train.jsonl"]
    assert result.files["samples/train.jsonl"].count("\n") == 2


def test_beir_uses_the_whole_corpus_and_only_test_queries():
    result = export_beir(_SAMPLES, _CORPUS)
    assert result.files["corpus.jsonl"].count("\n") == 2
    assert '"_id": "q2"' in result.files["queries.jsonl"]
    assert '"_id": "q1"' not in result.files["queries.jsonl"]
    assert result.files["qrels/test.tsv"] == "query-id\tcorpus-id\tscore\nq2\tseg_2\t1\n"


def test_beir_bytes_are_stable():
    assert export_beir(_SAMPLES, _CORPUS).files == export_beir(_SAMPLES, _CORPUS).files


def test_a_text_adapter_refuses_an_image_positive():
    image = ReleaseSample("q3", "Which figure?", "train", ["seg_3"], [], modality="image")
    corpus = ReleaseCorpus(segments=_CORPUS.segments, modalities=_CORPUS.modalities)
    with pytest.raises(AdapterError) as caught:
        export_flagembedding([*_SAMPLES, image], corpus)
    assert caught.value.issues[0].sample_id == "q3"


def test_the_text_subset_option_drops_the_image_sample_explicitly():
    image = ReleaseSample("q3", "Which figure?", "train", ["seg_3"], [], modality="image")
    result = export_flagembedding([*_SAMPLES, image], _CORPUS, text_only=True)
    assert "q3" not in result.files["train.jsonl"]
    assert result.files["train.jsonl"].count("\n") == 1


def test_sentence_transformers_has_one_column_per_negative():
    result = export_sentence_transformers(_SAMPLES, _CORPUS)
    line = result.files["train.jsonl"].splitlines()[0]
    assert '"anchor"' in line
    assert '"positive"' in line
    assert '"negative_1": "Sourdough needs wild yeast."' in line


def test_flagembedding_carries_the_teacher_scores():
    result = export_flagembedding(_SAMPLES, _CORPUS)
    line = result.files["train.jsonl"].splitlines()[0]
    assert '"pos_scores": [0.9]' in line
    assert '"neg_scores": [0.2]' in line
    assert '"pos": ["Notice is required thirty days before revocation."]' in line


def test_every_adapter_is_deterministic():
    for exporter in (export_beir, export_sentence_transformers, export_flagembedding):
        assert exporter(_SAMPLES, _CORPUS).files == exporter(list(reversed(_SAMPLES)), _CORPUS).files
    assert export_canonical(_SAMPLES, _CORPUS).files == export_canonical(_SAMPLES, _CORPUS).files


@pytest.mark.parametrize("exporter", [export_beir, export_flagembedding, export_sentence_transformers])
def test_text_adapters_reject_image_negatives_and_subset_removes_the_whole_sample(exporter):
    samples = [ReleaseSample("mixed", "Q", "test", ["seg_1"], ["image"]), _SAMPLES[1]]
    corpus = ReleaseCorpus({**_CORPUS.segments, "image": ""}, {**_CORPUS.modalities, "image": "image"})
    with pytest.raises(AdapterError) as error:
        exporter(samples, corpus)
    assert any(item.sample_id == "mixed" for item in error.value.issues)
    assert exporter(samples, corpus, text_only=True).files == exporter([_SAMPLES[1]], corpus).files


def test_sentence_transformers_preserves_all_positives_and_rejects_blank_negative_padding():
    sample = ReleaseSample("q", "Q", "train", ["seg_1", "seg_2"], ["seg_2"])
    assert export_sentence_transformers([sample], _CORPUS).files["train.jsonl"].count("\n") == 2
    with pytest.raises(AdapterError):
        export_sentence_transformers([sample, ReleaseSample("q2", "Q2", "train", ["seg_1"], [])], _CORPUS)


def test_same_split_order_is_stable_for_all_text_exports():
    samples = [
        ReleaseSample("q2", "B", "test", ["seg_2"], ["seg_1"]),
        ReleaseSample("q1", "A", "test", ["seg_1"], ["seg_2"]),
    ]
    for exporter in (export_canonical, export_beir, export_flagembedding, export_sentence_transformers):
        assert exporter(samples, _CORPUS).files == exporter(list(reversed(samples)), _CORPUS).files


@pytest.mark.parametrize(
    "name,exporter",
    [
        ("canonical", export_canonical),
        ("beir", export_beir),
        ("sentence_transformers", export_sentence_transformers),
        ("flagembedding", export_flagembedding),
    ],
)
def test_text_export_golden_bytes(name, exporter):
    expected = json.loads((Path(__file__).parents[1] / "fixtures" / "text_exports.json").read_text(encoding="utf-8"))[
        name
    ]
    actual = exporter(_SAMPLES, _CORPUS).files
    assert {path: value.encode("utf-8") for path, value in actual.items()} == {
        path: value.encode("utf-8") for path, value in expected.items()
    }
