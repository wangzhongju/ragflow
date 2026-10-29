"""Deployment CLI contracts using a fake Docker daemon (no services required)."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "docker/docker.sh"


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Linux Bash CLI")
class DockerCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ragflow-cli-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.script = self.path / "checkout/docker/docker.sh"
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.script)
        for name in ("scripts/init_env.py", "config/env.example"):
            target = self.script.parent / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "docker" / name, target)
        self.env_dir = self.path / "env with spaces"
        self.env_dir.mkdir()
        for role in ("app", "storage"):
            (self.env_dir / f"{role}.env").write_text("DUMMY=1\n")
        self.log = self.path / "calls.jsonl"
        docker = self.path / "docker"
        docker.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "with open(os.environ['CALL_LOG'], 'a') as f:\n"
            "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if '--images' in sys.argv: print('ragflow-local:test')\n"
            "if sys.argv[1:3] == ['image', 'inspect']: print('sha256:' + 'a' * 64)\n"
            "if os.environ.get('FAIL_APP') and 'ragflow-app' in sys.argv:\n"
            "    sys.exit(17)\n"
        )
        docker.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.path}:{os.environ['PATH']}",
                        RAGFLOW_ENV_DIR=str(self.env_dir), CALL_LOG=str(self.log),
                        COMPOSE_PROJECT_NAME="do-not-touch", COMPOSE_PROFILES="unrelated")

    def run_cli(self, *args, success=True):
        result = subprocess.run(["bash", str(self.script), *args], cwd=self.path,
                                env=self.env, text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_help_needs_no_env_or_daemon(self):
        (self.env_dir / "app.env").unlink()
        self.assertIn("into storage SERVICE", self.run_cli("help").stdout)
        self.assertEqual(self.calls(), [])

    def test_mutation_requires_role(self):
        self.run_cli("stop", success=False)
        self.assertEqual(self.calls(), [])

    def test_down_rejects_volume_deletion(self):
        self.run_cli("down", "storage", "-v", success=False)
        self.assertEqual(self.calls(), [])

    def test_missing_second_env_prevents_all_mutations(self):
        (self.env_dir / "app.env").unlink()
        self.run_cli("start", "all", success=False)
        self.assertTrue(all("config" in call for call in self.calls()))

    def test_invalid_app_config_prevents_storage_start(self):
        self.env["FAIL_APP"] = "1"
        self.run_cli("start", "all", success=False)
        self.assertTrue(all("config" in call for call in self.calls()))

    def test_single_host_start_orders_storage_before_app(self):
        self.run_cli("start", "all")
        calls = self.calls()
        ups = [call for call in calls if "up" in call]
        self.assertEqual(len(ups), 3)
        self.assertIn("ragflow-storage", ups[0])
        self.assertIn("mysql", ups[0])
        self.assertIn("kibana", ups[1])
        self.assertIn("ragflow-app", ups[2])
        for call in ups:
            self.assertIn("--wait", call)
            self.assertEqual(call[call.index("--pull") + 1], "never")

    def test_all_stop_orders_app_before_storage(self):
        self.run_cli("stop", "all")
        stops = [call for call in self.calls() if "stop" in call]
        self.assertIn("ragflow-app", stops[0])
        self.assertIn("ragflow-storage", stops[1])

    def test_all_recreate_stops_app_before_changing_storage(self):
        self.run_cli("recreate", "all")
        mutations = [call for call in self.calls() if "stop" in call or "up" in call]
        self.assertIn("ragflow-app", mutations[0])
        self.assertEqual(mutations[0][-1], "stop")
        self.assertIn("ragflow-storage", mutations[1])
        self.assertIn("--force-recreate", mutations[1])

    def test_into_uses_selected_service_shell(self):
        self.run_cli("into", "app")
        self.assertEqual(self.calls()[-1][-3:], ["exec", "ragflow", "bash"])
        self.run_cli("into", "storage", "mysql")
        self.assertEqual(self.calls()[-1][-3:], ["exec", "mysql", "sh"])

    def test_exec_preserves_command_arguments_and_project(self):
        self.run_cli("exec", "app", "ragflow", "printf", "%s", "a b; $(false)")
        call = self.calls()[-1]
        self.assertEqual(call[-6:], ["exec", "-T", "ragflow", "printf", "%s", "a b; $(false)"])
        self.assertEqual(call[call.index("--project-name") + 1], "ragflow-app")
        self.assertEqual(call[call.index("--env-file") + 1], str(self.env_dir / "app.env"))

    def test_init_matches_credentials_and_never_overwrites(self):
        for path in self.env_dir.iterdir():
            path.unlink()
        self.run_cli("init", "--app-ip", "192.0.2.91", "--storage-ip", "192.0.2.92", "--app-memory", "4g")
        app_file, storage_file = (self.env_dir / "app.env"), (self.env_dir / "storage.env")
        before = app_file.read_bytes(), storage_file.read_bytes()
        app = dict(line.split("=", 1) for line in app_file.read_text().splitlines())
        storage = dict(line.split("=", 1) for line in storage_file.read_text().splitlines())
        self.assertEqual(app["MYSQL_PASSWORD"], storage["MYSQL_PASSWORD"])
        self.assertEqual(app["MYSQL_HOST"], storage["STORAGE_IP"])
        self.assertEqual(app["APP_MEM_LIMIT"], "4g")
        self.assertNotIn("MYSQL_ROOT_PASSWORD", app)
        self.assertEqual(app_file.stat().st_mode & 0o777, 0o600)
        self.run_cli("init", "--app-ip", "192.0.2.91", "--storage-ip", "192.0.2.92", success=False)
        self.assertEqual(before, (app_file.read_bytes(), storage_file.read_bytes()))


if __name__ == "__main__":
    unittest.main()
