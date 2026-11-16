"""Emit the HTTP contract without opening databases or object storage."""

import json
from pathlib import Path

from fastapi import FastAPI

from datafactory.app.routes import router


def main() -> None:
    app = FastAPI(title="DataFactory", version="0.1.0")
    app.include_router(router, prefix="/api/factory/v1")
    document = json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"
    import sys

    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(document, encoding="utf-8")
    else:
        print(document, end="")


if __name__ == "__main__":
    main()
