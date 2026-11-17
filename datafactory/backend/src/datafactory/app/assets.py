"""Private asset responses, conditional requests and single byte ranges."""

import re

from fastapi import Response


def asset_response(data: bytes, mime: str, asset_id: str, headers) -> Response:
    size = len(data)
    etag = f'"{asset_id}"'
    response_headers = {
        "ETag": etag,
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-cache",
        "Vary": "Cookie",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
        "Content-Disposition": "attachment" if mime in {"text/html", "image/svg+xml"} else "inline",
    }
    if headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=response_headers)
    requested = headers.get("range")
    if requested and headers.get("if-range", etag) == etag:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
        start, end = 0, size - 1
        valid = bool(match and (match[1] or match[2]) and size)
        if valid and match:
            if not match[1]:
                valid = int(match[2]) > 0
                start = max(0, size - int(match[2]))
            else:
                start = int(match[1])
                end = min(end, int(match[2])) if match[2] else end
                valid = start <= end
        if not valid:
            return Response(status_code=416, headers={**response_headers, "Content-Range": f"bytes */{size}"})
        return Response(
            data[start : end + 1],
            status_code=206,
            media_type=mime,
            headers={**response_headers, "Content-Range": f"bytes {start}-{end}/{size}"},
        )
    return Response(data, media_type=mime, headers=response_headers)
