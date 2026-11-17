"""Deterministic, independently verifiable release archives."""

import hashlib
import io
import json
from pathlib import PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def json_bytes(value) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def fingerprint(value) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def build_archive(manifest: dict, adapter: str, files: dict[str, bytes]) -> bytes:
    payloads = dict(files)
    report = [
        f"# Release {manifest['release_id']}",
        "",
        f"Samples: {manifest['sample_count']}",
        f"Snapshot: {manifest['snapshot_id']}",
        f"Recipe version: {manifest['recipe_version_id']}",
        "",
        "## Gates",
        "",
    ]
    report.extend(
        f"- {gate['name']}: {'PASS' if gate['passed'] else 'FAIL'} ({gate['level']}) — {gate['detail']}"
        for gate in manifest["gates"]
    )
    payloads["report.md"] = ("\n".join(report) + "\n").encode()
    payloads["manifest.json"] = json_bytes(
        {
            **manifest,
            "adapter": adapter,
            "files": {
                name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
                for name, data in sorted(payloads.items())
            },
        }
    )
    payloads["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(payloads.items())
    ).encode()
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in sorted(payloads.items()):
            if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts or "\\" in name:
                raise ValueError("Export filenames must stay within the archive.")
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    return output.getvalue()
