#!/usr/bin/env python3
"""Download pinned official resources into third_partys; reuse verified local files."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import time
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docker/config/artifacts.json"


def digest(path, algorithm="sha256"):
    result = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def cache_path(root, relative):
    parts = PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts or "\\" in relative:
        raise ValueError(f"Unsafe artifact path: {relative}")
    path = root.joinpath(*parts.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Artifact escapes cache: {relative}")
    return path


def valid(path, item):
    return path.is_file() and path.stat().st_size == item["size"] and digest(path) == item["sha256"]


def ensure_file(root, item, offline=False):
    path = cache_path(root, item["path"])
    if valid(path, item):
        print(f"Cached: {item['path']}", flush=True)
        return path
    if offline:
        raise ValueError(f"Missing or corrupt artifact: {item['path']}; run docker.sh fetch")
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        temporary = None
        try:
            request = urllib.request.Request(item["url"], headers={"User-Agent": "RAGFlow-artifacts/1"})
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".part", delete=False) as out:
                temporary = Path(out.name)
                with urllib.request.urlopen(request, timeout=90) as response:
                    shutil.copyfileobj(response, out, length=1024 * 1024)
            if not valid(temporary, item):
                raise ValueError(f"Checksum/size mismatch for {item['path']}")
            temporary.replace(path)
            print(f"Downloaded: {item['path']}", flush=True)
            return path
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def extract_nltk(root, item, offline=False):
    archive = cache_path(root, item["path"])
    destination = cache_path(root, item["extract_to"])
    receipt = root / ".receipts" / (archive.stem + ".json")
    record = {}
    if receipt.is_file():
        try:
            record = json.loads(receipt.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
        if isinstance(record, dict) and record.get("archive_sha256") == item["sha256"] and record.get("files") and all(
            cache_path(destination, name).is_file() and digest(cache_path(destination, name)) == checksum
            for name, checksum in record["files"].items()
        ):
            return
    if offline:
        raise ValueError(f"Incomplete extracted NLTK package: {archive.stem}; run docker.sh fetch")
    destination.mkdir(parents=True, exist_ok=True)
    checksums = {}
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            path = cache_path(destination, member.filename)
            if member.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with source.open(member) as inp, path.open("wb") as out:
                shutil.copyfileobj(inp, out)
            checksums[member.filename] = digest(path)
    receipt.parent.mkdir(exist_ok=True)
    receipt.write_text(json.dumps({"archive_sha256": item["sha256"], "files": checksums}, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Extracted NLTK: {archive.stem}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate without downloading or changing files")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "third_partys")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    root = args.cache_dir.resolve()
    if not args.check:
        root.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda item: ensure_file(root, item, args.check), manifest["files"]))
    for item in manifest["files"]:
        if "extract_to" in item:
            extract_nltk(root, item, args.check)
    # python-tika expects an MD5 file beside the JAR. Derive it from the SHA256-verified artifact.
    jar = root / "tika/tika-server-standard-3.3.0.jar"
    checksum = digest(jar, "md5")
    md5_file = jar.with_suffix(".jar.md5")
    if args.check:
        if not md5_file.is_file() or md5_file.read_text().strip() != checksum:
            raise ValueError("Missing or incorrect Tika MD5 file; run docker.sh fetch")
    elif not md5_file.is_file() or md5_file.read_text().strip() != checksum:
        md5_file.write_text(checksum + "\n", encoding="ascii")
    print(f"Verified {len(manifest['files'])} artifacts in {root}")


if __name__ == "__main__":
    main()
