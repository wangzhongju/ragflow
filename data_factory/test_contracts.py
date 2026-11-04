"""Regression cases for exclusion gates, partition families and adapter contracts."""

import unittest
from unittest.mock import patch

from .embedding import overlaps_positive, prepare
from .generators import candidates
from .schema import Sample, settings
from .source import FactoryError


class ContractTest(unittest.TestCase):
    def test_figure_context_cannot_become_negative(self):
        positive = "Access is granted through a policy decision point and corresponding policy enforcement point."
        figure = positive + " Figure 1. A network diagram depicts the untrusted and implicit trust zones."
        self.assertTrue(overlaps_positive(positive, figure))
        evidence = {}
        for eid, text in [
            ("d/p", positive),
            ("d/image", figure),
            ("d/hard", "The policy engine grants or denies access using trust algorithms."),
            ("d/irrelevant", "Measurement uncertainty depends on the coverage factor."),
        ]:
            evidence[eid] = {"id": eid, "text": text, "doc": "d", "kb": "k", "split": "train", "sha256": eid, "questions": []}

        class Source:
            def retrieve(self, *args):
                return {"chunks": [{"document_id": "d", "id": eid.split("/")[1], "content": item["text"]} for eid, item in evidence.items()]}

            def rerank(self, *args):
                return {"scores": [0.99, 0.98, 0.95, 0.7], "model_name": "fixture"}

        config = settings({"negative_count": 1, "rerank_id": "fixture"})
        with patch("data_factory.generators.invoke", side_effect=lambda ds, unit, kind, payload, config, operation, check: operation()):
            result = candidates({"query": [{"type": "text", "text": "Which access components are used?"}], "positives": ["d/p"]}, evidence, "fixture", config, Source(), lambda: None)
        self.assertEqual(result["negatives"][0]["evidence_id"], "d/irrelevant")
        self.assertIn("d/image", {i["evidence_id"] for i in result["uncertain_candidates"]})
        self.assertIn("d/hard", {i["evidence_id"] for i in result["uncertain_candidates"]})

    def test_repeated_source_families_cannot_split(self):
        docs = []
        for doc, name, text in [("a", "manual-v1.txt", "Independent original source."), ("b", "manual-v2.txt", "Revised content."), ("c", "copy.txt", "Independent original source.")]:
            docs.append({"doc": doc, "kb": "k", "name": name, "chunks": [{"id": "1", "content": text, "questions": []}]})
        evidence = prepare(docs, settings({}), lambda: None)
        self.assertEqual(len({e["group_id"] for e in evidence.values()}), 1)
        self.assertEqual(len({e["split"] for e in evidence.values()}), 1)

    def test_unknown_payload_fields_are_rejected(self):
        sample = {
            "schema_version": 2,
            "sample_id": "1",
            "revision": 1,
            "task": "embedding",
            "snapshot_id": "s",
            "group_id": "d",
            "split": "train",
            "evidence_ids": ["d/a"],
            "provenance": {},
            "payload": {"query": [{"type": "text", "text": "question"}], "positives": ["d/a"], "negatives": [], "unexpected": "payload"},
        }
        with self.assertRaises(ValueError):
            Sample.model_validate(sample)
        with self.assertRaises(FactoryError):
            settings({"query_mode": "llm"})
