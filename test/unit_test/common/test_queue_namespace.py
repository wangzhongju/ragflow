"""Queue namespace configuration must agree across API and worker processes."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class QueueNamespaceTest(unittest.TestCase):
    def namespace(self, mode, name=None):
        env = dict(os.environ, APP_MODE=mode)
        env.pop("RAGFLOW_QUEUE_NAME", None)
        if name is not None:
            env["RAGFLOW_QUEUE_NAME"] = name
        return subprocess.run([sys.executable, "-c", "from common.constants import SVR_QUEUE_NAME; print(SVR_QUEUE_NAME)"], cwd=ROOT, env=env, text=True, capture_output=True, check=False)

    def test_development_and_production_do_not_share_default(self):
        self.assertEqual(self.namespace("prod").stdout.strip(), "te")
        self.assertEqual(self.namespace("dev").stdout.strip(), "te.dev")

    def test_explicit_namespace_is_reproducible_for_each_process(self):
        self.assertEqual(self.namespace("dev", "te.dev91").stdout.strip(), "te.dev91")
        self.assertEqual(self.namespace("dev", "te.dev91").stdout.strip(), "te.dev91")

    def test_development_refuses_production_or_invalid_namespace(self):
        for name in ("te", "", "../queue", "a b", "*"):
            with self.subTest(name=name):
                self.assertNotEqual(self.namespace("dev", name).returncode, 0)
