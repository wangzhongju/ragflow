"""The M2 adapters keep image paths consistent with the asset digest."""

import pytest

from datafactory.adapters import AdapterError, ReleaseCorpus, ReleaseSample, export_mm_retrieval, export_ms_swift

_CORPUS = ReleaseCorpus(
    segments={"seg_1": "A figure.", "seg_2": "A caption."}, modalities={"seg_1": "image", "seg_2": "text"}
)


def test_mm_retrieval_names_images_by_digest():
    sample = ReleaseSample("q1", "Which figure?", "train", ["seg_1"], ["seg_2"], modality="image")
    result = export_mm_retrieval([sample], _CORPUS, {"seg_1": "sha256:abcd"})
    assert '"image": "images/abcd"' in result.files["samples.jsonl"]


def test_mm_retrieval_refuses_a_missing_asset():
    sample = ReleaseSample("q1", "Which figure?", "train", ["seg_1"], [], modality="image")
    with pytest.raises(AdapterError):
        export_mm_retrieval([sample], _CORPUS, {})


def test_ms_swift_wraps_messages():
    sample = ReleaseSample("q1", "What is shown?", "train", ["seg_2"], ["seg_1"])
    result = export_ms_swift([sample], _CORPUS)
    assert '"positive_messages"' in result.files["samples.jsonl"]
    assert "A caption." in result.files["samples.jsonl"]
