"""Authorized run snapshots over SSE; each iteration releases its database session."""

import asyncio
import hashlib

from datafactory.app.auth import read_cookie
from datafactory.core.errors import DFError
from datafactory.pipeline.service import ProductionService


async def run_stream(request, project_id, run_id, user_id):
    previous = request.headers.get("Last-Event-ID", "")
    while not await request.is_disconnected():
        if read_cookie(request, request.app.state.settings.session_secret) != user_id:
            yield "event: access-revoked\ndata: {}\n\n"
            return
        try:
            async with request.app.state.sessions() as session:
                run = await ProductionService(session, None).get_run(project_id, run_id, user_id)
        except DFError:
            yield "event: access-revoked\ndata: {}\n\n"
            return
        payload = run.model_dump_json()
        revision = hashlib.sha256(payload.encode()).hexdigest()
        if revision != previous:
            yield f"id: {revision}\nevent: run\ndata: {payload}\n\n"
            previous = revision
        else:
            yield ": heartbeat\n\n"
        if run.status not in {"queued", "running"}:
            return
        await asyncio.sleep(5)
