"""Stateless document parsing for external agents using the existing parser."""

from pathlib import PurePosixPath

MAX_FILE_BYTES = 20 * 1024 * 1024
SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".doc", ".txt", ".md", ".markdown", ".html", ".htm", ".csv", ".xls", ".xlsx", ".json", ".jsonl", ".epub")
LAYOUT_MODES = ("Plain Text", "DeepDOC")


def validate_options(filename, layout_recognize):
    name = PurePosixPath((filename or "").replace("\\", "/")).name
    if not name or len(name) > 255 or any(ord(c) < 32 for c in name):
        raise ValueError("A valid filename is required")
    if PurePosixPath(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("Unsupported file extension")
    if layout_recognize not in LAYOUT_MODES:
        raise ValueError("layout_recognize must be Plain Text or DeepDOC")
    return name


def parse_document(filename, blob, tenant_id, layout_recognize="Plain Text"):
    name = validate_options(filename, layout_recognize)
    if not blob or len(blob) > MAX_FILE_BYTES:
        raise ValueError("File must contain between 1 byte and 20 MiB")
    from api.db.services.file_service import FileService

    content = FileService.parse(name, blob, img_base64=False, tenant_id=tenant_id, layout_recognize=layout_recognize)
    return {"filename": name, "size": len(blob), "format": "text", "content": content, "layout_recognize": layout_recognize}
