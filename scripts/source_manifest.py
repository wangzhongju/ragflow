#!/usr/bin/env python3
"""Print source hashes for cross-host comparison; never read ignored private files."""

import hashlib
import json
import os
from pathlib import Path
import sys

from project_inventory import ROOT, source_files


BINARY = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".msg",
          ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".gz",
          ".tar", ".jar", ".pkl", ".bin", ".onnx", ".woff", ".woff2", ".ttf",
          ".mp3", ".wav", ".mp4", ".so", ".a", ".dll", ".exe"}


def link_target(path):
    try:
        return os.readlink(path)
    except (OSError, ValueError):
        if os.name != "nt":
            raise
    # WSL-created LX symlinks have a different Windows reparse tag. Read their
    # actual target instead of pretending that the Git index proves parity.
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
                                      wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    kernel.DeviceIoControl.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0, 7, None, 3, 0x02200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        buffer = ctypes.create_string_buffer(16384)
        returned = wintypes.DWORD()
        if not kernel.DeviceIoControl(handle, 0x900A8, None, 0, buffer, len(buffer), ctypes.byref(returned), None):
            raise ctypes.WinError(ctypes.get_last_error())
        data = buffer.raw[:returned.value]
        if int.from_bytes(data[:4], "little") != 0xA000001D or data[8:12] != b"\x02\x00\x00\x00":
            raise ValueError(f"Unsupported reparse point: {path}")
        size = int.from_bytes(data[4:6], "little")
        return data[12:8 + size].decode("utf-8")
    finally:
        kernel.CloseHandle(handle)


def main():
    manifest = {}
    for name, mode in source_files().items():
        path = ROOT / name
        if mode == "120000":
            data = link_target(path).encode("utf-8")
            kind = "symlink"
        else:
            data = path.read_bytes()
            kind = "file"
            if Path(name).suffix.lower() not in BINARY and b"\0" not in data:
                try:
                    data.decode("utf-8")
                except UnicodeDecodeError:
                    pass
                else:
                    data = data.replace(b"\r\n", b"\n")
        manifest[name] = {"kind": kind, "sha256": hashlib.sha256(data).hexdigest()}
    output = json.dumps({"normalization": "UTF-8 text CRLF to LF; binary bytes and symlink targets unchanged",
                         "files": manifest}, ensure_ascii=False, sort_keys=True, indent=2)
    sys.stdout.buffer.write((output + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
