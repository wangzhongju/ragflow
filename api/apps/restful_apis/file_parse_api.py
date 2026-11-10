"""Authenticated, stateless file parsing for external agents."""

import logging

from quart import request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from api.apps import AUTH_API, current_user, login_required
from api.apps.services.file_parse_service import LAYOUT_MODES, MAX_FILE_BYTES, SUPPORTED_EXTENSIONS, parse_document, validate_options
from api.utils.api_utils import get_result
from common.misc_utils import thread_pool_exec_long_time

logger = logging.getLogger(__name__)


@manager.route("/files/parse", methods=["GET"])  # noqa: F821
@login_required(auth_types=[AUTH_API])
async def parsing_capabilities():
    return get_result(data={"extensions": SUPPORTED_EXTENSIONS, "max_file_bytes": MAX_FILE_BYTES, "layout_modes": LAYOUT_MODES, "format": "text"})


@manager.route("/files/parse", methods=["POST"])  # noqa: F821
@login_required(auth_types=[AUTH_API])
async def parse_file():
    if request.mimetype != "multipart/form-data":
        return get_result(code=415, message="Use multipart/form-data with one file field"), 415
    request.max_content_length = min(request.max_content_length or MAX_FILE_BYTES + 65536, MAX_FILE_BYTES + 65536)
    try:
        if request.content_length is not None and request.content_length > request.max_content_length:
            raise RequestEntityTooLarge()
        files = await request.files
        form = await request.form
        if set(files) != {"file"} or len(files.getlist("file")) != 1:
            raise ValueError("Exactly one file field is required")
        if set(form) - {"layout_recognize"} or len(form.getlist("layout_recognize")) > 1:
            raise ValueError("Only one optional layout_recognize field is accepted")
        upload = files["file"]
        layout = form.get("layout_recognize", "Plain Text")
        name = validate_options(upload.filename, layout)
        blob = upload.read(MAX_FILE_BYTES + 1)
        if len(blob) > MAX_FILE_BYTES:
            raise RequestEntityTooLarge()
        if not blob:
            raise ValueError("File is empty")
    except RequestEntityTooLarge:
        return get_result(code=413, message="File limit is 20 MiB; multipart request limit is 20 MiB + 64 KiB"), 413
    except (ValueError, BadRequest) as exc:
        return get_result(code=400, message=str(exc)), 400

    try:
        result = await thread_pool_exec_long_time(parse_document, name, blob, current_user.id, layout)
        return get_result(data=result)
    except Exception:
        logger.exception("External file parsing failed")
        return get_result(code=422, message="Parsing failed; check the document and server parser configuration"), 422
