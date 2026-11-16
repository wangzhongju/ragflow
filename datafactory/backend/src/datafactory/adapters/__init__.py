"""Export adapters.

An adapter reads a frozen release and writes one training format. It never
changes the release. A text adapter refuses a release that contains image
positives instead of dropping them, unless the caller explicitly asks for the
text subset.
"""

import json
from dataclasses import dataclass, field

from datafactory.domain.content import Modality


@dataclass
class ReleaseSample:
    """One frozen training sample, already split."""

    query_id: str
    query: str
    split: str
    positives: list[str]
    negatives: list[str]
    positive_scores: list[float] = field(default_factory=list)
    negative_scores: list[float] = field(default_factory=list)
    modality: Modality = "text"


@dataclass
class ReleaseCorpus:
    """The full snapshot corpus. Evaluation uses all of it, not just the test split."""

    segments: dict[str, str]
    modalities: dict[str, Modality] = field(default_factory=dict)


@dataclass
class ExportIssue:
    """One reason an adapter refuses a release."""

    sample_id: str
    message: str


@dataclass
class ExportResult:
    """The files an adapter produced, keyed by relative path."""

    files: dict[str, str]
    issues: list[ExportIssue] = field(default_factory=list)


class AdapterError(ValueError):
    """The release does not fit the adapter. ``issues`` names the samples."""

    def __init__(self, issues: list[ExportIssue]) -> None:
        self.issues = issues
        super().__init__(f"{len(issues)} samples cannot be exported.")


def validate_text(samples: list[ReleaseSample], corpus: ReleaseCorpus, text_only: bool) -> list[ExportIssue]:
    """Image positives block a text export unless the caller asked for the text subset."""
    if text_only:
        return []
    issues = []
    for sample in samples:
        if sample.modality != "text":
            issues.append(ExportIssue(sample.query_id, f"Sample {sample.query_id} is {sample.modality}, not text."))
            continue
        for segment_id in sample.positives:
            modality = corpus.modalities.get(segment_id, "text")
            if modality != "text":
                issues.append(ExportIssue(sample.query_id, f"Positive {segment_id} is {modality}."))
    return issues


def _text_samples(samples: list[ReleaseSample], corpus: ReleaseCorpus, text_only: bool) -> list[ReleaseSample]:
    issues = validate_text(samples, corpus, text_only)
    if issues and not text_only:
        raise AdapterError(issues)
    blocked = {issue.sample_id for issue in issues}
    return [sample for sample in samples if sample.query_id not in blocked and sample.modality == "text"]


def export_canonical(samples: list[ReleaseSample], corpus: ReleaseCorpus) -> ExportResult:
    """The release as JSONL, one file per split. Every modality is kept."""
    files: dict[str, list[str]] = {}
    for sample in samples:
        files.setdefault(f"samples/{sample.split}.jsonl", []).append(
            json.dumps(
                {
                    "query_id": sample.query_id,
                    "query": sample.query,
                    "positives": sample.positives,
                    "negatives": sample.negatives,
                    "modality": sample.modality,
                },
                ensure_ascii=False,
            )
        )
    return ExportResult({name: "\n".join(lines) + "\n" for name, lines in sorted(files.items())})


def export_beir(samples: list[ReleaseSample], corpus: ReleaseCorpus, text_only: bool = False) -> ExportResult:
    """A BEIR evaluation set: the whole corpus, the test queries and their qrels.

    The corpus contains every segment, so the evaluation has the real distractors.
    Only the test split becomes queries.
    """
    kept = _text_samples(samples, corpus, text_only)
    corpus_lines = [
        json.dumps({"_id": segment_id, "title": "", "text": text}, ensure_ascii=False)
        for segment_id, text in sorted(corpus.segments.items())
        if corpus.modalities.get(segment_id, "text") == "text"
    ]
    test = [sample for sample in kept if sample.split == "test"]
    query_lines = [json.dumps({"_id": sample.query_id, "text": sample.query}, ensure_ascii=False) for sample in test]
    qrels = ["query-id\tcorpus-id\tscore"]
    for sample in test:
        for segment_id in sample.positives:
            qrels.append(f"{sample.query_id}\t{segment_id}\t1")
    return ExportResult(
        {
            "corpus.jsonl": "\n".join(corpus_lines) + "\n",
            "queries.jsonl": "\n".join(query_lines) + ("\n" if query_lines else ""),
            "qrels/test.tsv": "\n".join(qrels) + "\n",
        }
    )


def export_sentence_transformers(
    samples: list[ReleaseSample], corpus: ReleaseCorpus, text_only: bool = False
) -> ExportResult:
    """Triplets with a fixed number of negative columns, one file per split."""
    kept = _text_samples(samples, corpus, text_only)
    width = max((len(sample.negatives) for sample in kept), default=0)
    files: dict[str, list[str]] = {}
    for sample in kept:
        row = {"anchor": sample.query, "positive": corpus.segments.get(sample.positives[0], "")}
        for index in range(width):
            segment_id = sample.negatives[index] if index < len(sample.negatives) else ""
            row[f"negative_{index + 1}"] = corpus.segments.get(segment_id, "") if segment_id else ""
        files.setdefault(f"{sample.split}.jsonl", []).append(json.dumps(row, ensure_ascii=False))
    return ExportResult({name: "\n".join(lines) + "\n" for name, lines in sorted(files.items())})


def export_flagembedding(samples: list[ReleaseSample], corpus: ReleaseCorpus, text_only: bool = False) -> ExportResult:
    """FlagEmbedding JSONL with teacher scores, one file per split."""
    kept = _text_samples(samples, corpus, text_only)
    files: dict[str, list[str]] = {}
    for sample in kept:
        row = {
            "query": sample.query,
            "pos": [corpus.segments.get(segment_id, "") for segment_id in sample.positives],
            "neg": [corpus.segments.get(segment_id, "") for segment_id in sample.negatives],
            "pos_scores": sample.positive_scores,
            "neg_scores": sample.negative_scores,
        }
        files.setdefault(f"{sample.split}.jsonl", []).append(json.dumps(row, ensure_ascii=False))
    return ExportResult({name: "\n".join(lines) + "\n" for name, lines in sorted(files.items())})


def export_mm_retrieval(samples: list[ReleaseSample], corpus: ReleaseCorpus, assets: dict[str, str]) -> ExportResult:
    """Multimodal retrieval JSONL. Images are named by their SHA-256.

    ``assets`` maps a segment id to ``sha256:<hex>``. Each image is written as
    ``images/<hex>``, so the relative path and the digest agree. A sample whose
    image asset is missing is refused instead of exported without it.
    """
    issues = []
    lines = []
    for sample in samples:
        image = assets.get(sample.positives[0]) if sample.modality != "text" else None
        if sample.modality != "text" and image is None:
            issues.append(ExportIssue(sample.query_id, f"Sample {sample.query_id} has no image asset."))
            continue
        record = {"query": {"text": sample.query}, "pos": sample.positives, "neg": sample.negatives}
        if image:
            record["query"]["image"] = f"images/{image.removeprefix('sha256:')}"
        lines.append(json.dumps(record, ensure_ascii=False))
    if issues:
        raise AdapterError(issues)
    return ExportResult({"samples.jsonl": "\n".join(lines) + "\n"})


def export_ms_swift(samples: list[ReleaseSample], corpus: ReleaseCorpus) -> ExportResult:
    """ms-swift embedding JSONL. Positives and negatives are message lists."""
    lines = []
    for sample in samples:
        record = {
            "messages": [{"role": "user", "content": sample.query}],
            "positive_messages": [
                [{"role": "user", "content": corpus.segments.get(segment_id, "")}] for segment_id in sample.positives
            ],
            "negative_messages": [
                [{"role": "user", "content": corpus.segments.get(segment_id, "")}] for segment_id in sample.negatives
            ],
        }
        lines.append(json.dumps(record, ensure_ascii=False))
    return ExportResult({"samples.jsonl": "\n".join(lines) + "\n"})
