#!/usr/bin/env python3
"""Offline checks for a mounted Python deployment; run inside the application."""

import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    root = Path("/ragflow")
    results = {}

    def check(name, operation):
        try:
            detail = operation()
            results[name] = {"ok": True, "detail": detail}
        except Exception as error:
            results[name] = {"ok": False, "error": str(error)}

    def source():
        required = ["api/ragflow_server.py", "rag/svr/task_executor.py", "common/token_utils.py",
                    "docker/runtime/entrypoint-mounted.sh", "conf/llm_factories.json"]
        for path in required:
            if not (root / path).is_file():
                raise FileNotFoundError(path)
        return required

    def python():
        if sys.version_info < (3, 13):
            raise RuntimeError("Python 3.13+ is required")
        if str(Path(sys.executable).resolve()).startswith("/root/"):
            raise RuntimeError("Python interpreter still resides under /root")
        for name in ("quart", "peewee", "numpy", "onnxruntime", "pymysql", "valkey", "minio"):
            importlib.import_module(name)
        return {"version": sys.version.split()[0], "executable": str(Path(sys.executable).resolve())}

    def tika():
        jar = root / "tika-server-standard-3.3.0.jar"
        expected = jar.with_suffix(".jar.md5").read_text().strip().split()[0]
        with jar.open("rb") as stream:
            actual = hashlib.file_digest(stream, "md5").hexdigest()
        if expected.lower() != actual:
            raise RuntimeError("Tika checksum mismatch")
        return {"bytes": jar.stat().st_size, "md5": actual}

    def tokenizer():
        cache = root / "9b5ad71b2ce5302211f9c61530b329a4922fc6a4"
        if not cache.is_file():
            raise FileNotFoundError(cache)
        from common.token_utils import get_encoder
        encoded = get_encoder().encode("RAGFlow 离线分词检查")
        if not encoded:
            raise RuntimeError("Empty encoding")
        return {"cache_bytes": cache.stat().st_size, "token_count": len(encoded)}

    def models():
        paths = sorted((root / "rag/res/deepdoc").glob("*.onnx"))
        if len(paths) < 7 or any(path.stat().st_size < 1024 for path in paths):
            raise RuntimeError("Expected at least seven nonempty ONNX models")
        return [path.name for path in paths]

    def frontend():
        index = root / "web/dist/index.html"
        if not index.is_file() or index.stat().st_size == 0:
            raise FileNotFoundError(index)
        return {"index_bytes": index.stat().st_size}

    def workspace():
        with tempfile.TemporaryFile(dir=root, prefix=".runtime-check-") as stream:
            stream.write(b"mounted workspace writable\n")
            stream.flush()
            owner = os.fstat(stream.fileno()).st_uid
        if owner != os.getuid():
            raise RuntimeError("Workspace file owner differs from caller")
        return {"uid": os.getuid(), "gid": os.getgid(), "created_file_uid": owner}

    def nltk():
        import nltk
        tokens = nltk.word_tokenize("RAGFlow runtime check.")
        return {"token_count": len(tokens)}

    def tools():
        names = ("sudo", "vim", "apt-get", "apt-cache", "bash", "git", "less", "ip", "ping")
        for name in names:
            if not shutil.which(name):
                raise FileNotFoundError(name)
        if not Path("/usr/share/bash-completion/bash_completion").is_file():
            raise FileNotFoundError("bash-completion")
        subprocess.run(["sudo", "-n", "true"], check=True, capture_output=True)
        policy = subprocess.check_output(["apt-cache", "policy", "cmake"], text=True,
                                         env={**os.environ, "LC_ALL": "C"})
        candidates = [line.strip() for line in policy.splitlines() if "Candidate:" in line]
        if not candidates or "(none)" in candidates[0]:
            raise RuntimeError("apt package index is missing; run sudo apt-get update")
        return {"commands": names, "cmake": candidates[0]}

    for name, operation in (("mounted_source", source), ("python", python), ("tika", tika),
                            ("tokenizer", tokenizer), ("ocr_models", models),
                            ("frontend", frontend), ("workspace_write", workspace), ("nltk", nltk),
                            ("interactive_tools", tools)):
        check(name, operation)
    ok = all(result["ok"] for result in results.values())
    print(json.dumps({"ok": ok, "checks": results}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
