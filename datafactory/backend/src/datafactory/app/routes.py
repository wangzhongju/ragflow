"""HTTP routes for the platform's implemented resource and production services.

Routes call services and return declared response models. They hold no
business rules.
"""

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, SecretStr

from datafactory.app.auth import SESSION_TTL, current_user, session_cookie
from datafactory.core.errors import Forbidden, GatewayUnavailable, Unauthorized
from datafactory.core.settings import GatewaySettings, Settings
from datafactory.corpus.snapshot import SnapshotBuilder, drifted_documents
from datafactory.domain.content import HealthReport, Segment
from datafactory.engine.recipes import RecipeRecord, RecipeRepository, RecipeSummary
from datafactory.gateway.client import GatewayClient
from datafactory.gateway.dto import Dataset, DocumentPage, Model, Session
from datafactory.pipeline.service import (
    DatasetRecord,
    OverviewRecord,
    ProductionService,
    ReleaseRecord,
    RunMetrics,
    RunRecord,
    SampleRecord,
)
from datafactory.store.projects import Member, ProjectRepository
from datafactory.store.snapshots import SnapshotRepository

router = APIRouter()


@router.get("/assets/{asset_id}")
async def asset_download(asset_id: str, request: Request, user_id: str = Depends(current_user)) -> Response:
    from datafactory.app.assets import asset_response
    from datafactory.store.assets import read_asset

    data, mime = await read_asset(request.state.session, request.app.state.objects, asset_id, user_id)
    return asset_response(data, mime, asset_id, request.headers)


# The gateway reports refusal with its own code, which is not the HTTP status.
_GATEWAY_FORBIDDEN = 108


class Me(BaseModel):
    """The signed-in user."""

    user_id: str
    tenant_ids: list[str]
    nickname: str
    lang: str


class LoginIn(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: SecretStr = Field(min_length=1, max_length=4096, description="RSA-encrypted RAGFlow password.")


class ProjectIn(BaseModel):
    """Fields a client sends to create a project."""

    name: str
    description: str = ""


class ProjectPatch(BaseModel):
    """Fields a client sends to change a project."""

    name: str
    description: str | None = None


class ProjectOut(BaseModel):
    """A project as returned to clients."""

    id: str
    name: str
    description: str
    owner_id: str
    role: str


class MemberIn(BaseModel):
    """One member in a replacement member list."""

    user_id: str
    role: str


class MemberOut(BaseModel):
    """One member as returned to clients."""

    user_id: str
    role: str


def _projects(request: Request) -> ProjectRepository:
    return ProjectRepository(request.state.session)


def _snapshots(request: Request) -> SnapshotRepository:
    return SnapshotRepository(request.state.session, getattr(request.app.state, "objects", None))


def _gateway(request: Request, user_id: str) -> GatewayClient:
    settings: Settings = request.app.state.settings
    gateway_settings = GatewaySettings(
        gateway_base_url=settings.gateway_base_url,
        gateway_service_key=settings.gateway_service_key,
        gateway_version=settings.gateway_version,
        gateway_timeout_s=settings.gateway_timeout_s,
    )
    return GatewayClient(gateway_settings, user_id, request.headers.get("x-request-id", ""))


def _project_out(project) -> ProjectOut:
    return ProjectOut(
        id=project.id, name=project.name, description=project.description, owner_id=project.owner_id, role=project.role
    )


def _issue_session(request: Request, response: Response, session: Session) -> Me:
    name, value = session_cookie(session.user_id, request.app.state.settings.session_secret)
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        name,
        value,
        httponly=True,
        samesite="lax",
        path="/api/factory/",
        max_age=SESSION_TTL,
        secure=request.url.scheme == "https",
    )
    return Me(user_id=session.user_id, tenant_ids=session.tenant_ids, nickname=session.nickname, lang=session.lang)


@router.post("/session", response_model=Me)
async def sign_in(body: LoginIn, request: Request, response: Response) -> Me:
    """Start a DataFactory session with RAGFlow account credentials."""
    session = await _gateway(request, "").session_from_password(body.email, body.password.get_secret_value())
    return _issue_session(request, response, session)


@router.get("/me", response_model=Me)
async def me(request: Request, response: Response) -> Me:
    """Read the platform session or bootstrap it with an existing RAGFlow login."""
    user_id = request.scope.get("df_user_id", "")
    if user_id:
        response.headers["Cache-Control"] = "no-store"
        return Me(user_id=user_id, tenant_ids=[], nickname="", lang="")
    authorization = request.headers.get("authorization", "")
    if not authorization:
        raise Unauthorized("Sign in to DataFactory first.")
    session = await _gateway(request, "").session_from_token(authorization)
    return _issue_session(request, response, session)


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectIn, request: Request, response: Response, user_id: str = Depends(current_user)
) -> ProjectOut:
    """Create a project owned by the caller.

    Repeating the call with the same Idempotency-Key and body returns the
    project created the first time instead of a second one.
    """
    key = request.headers.get("idempotency-key", "")
    project = await _projects(request).create(user_id, body.name, body.description, key)
    return _project_out(project)


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(request: Request, user_id: str = Depends(current_user)) -> list[ProjectOut]:
    """Projects the caller belongs to."""
    return [_project_out(project) for project in await _projects(request).list_for(user_id)]


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, request: Request, user_id: str = Depends(current_user)) -> ProjectOut:
    """One project, when the caller is a member."""
    return _project_out(await _projects(request).get(project_id, user_id))


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: str, body: ProjectPatch, request: Request, user_id: str = Depends(current_user)
) -> ProjectOut:
    """Rename a project. Editors and owners only."""
    project = await _projects(request).rename(project_id, user_id, body.name, body.description)
    return _project_out(project)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: str, request: Request, user_id: str = Depends(current_user)) -> Response:
    """Delete a project. The owner only."""
    await _projects(request).delete(project_id, user_id)
    return Response(status_code=204)


@router.get("/projects/{project_id}/members", response_model=list[MemberOut])
async def list_members(project_id: str, request: Request, user_id: str = Depends(current_user)) -> list[MemberOut]:
    """Members of a project."""
    return [
        MemberOut(user_id=member.user_id, role=member.role)
        for member in await _projects(request).members(project_id, user_id)
    ]


@router.put("/projects/{project_id}/members", response_model=list[MemberOut])
async def replace_members(
    project_id: str, body: list[MemberIn], request: Request, user_id: str = Depends(current_user)
) -> list[MemberOut]:
    """Replace the member list. The owner only, and ownership stays put."""
    members = [Member(item.user_id, item.role) for item in body]
    saved = await _projects(request).set_members(project_id, user_id, members)
    return [MemberOut(user_id=member.user_id, role=member.role) for member in saved]


@router.get("/ragflow/datasets", response_model=list[Dataset])
async def ragflow_datasets(request: Request, user_id: str = Depends(current_user)) -> list[Dataset]:
    """Knowledge bases the caller can read in RAGFlow."""
    return await _gateway(request, user_id).list_datasets()


@router.get("/ragflow/datasets/{kb_id}/documents", response_model=DocumentPage)
async def ragflow_documents(
    kb_id: str, request: Request, cursor: str | None = None, user_id: str = Depends(current_user)
) -> DocumentPage:
    """One page of documents. RAGFlow enforces access, so a foreign base returns 403."""
    try:
        return await _gateway(request, user_id).list_documents(kb_id, cursor)
    except GatewayUnavailable as exc:
        if exc.gateway_code == _GATEWAY_FORBIDDEN:
            raise Forbidden(exc.message) from exc
        raise


class SnapshotIn(BaseModel):
    """What a client sends to freeze a corpus."""

    name: str
    sources: list[dict]


class SnapshotOut(BaseModel):
    """A snapshot as returned to clients. ``stats`` carries the health report."""

    id: str
    project_id: str
    name: str
    status: str
    sources: list[dict]
    vector_profile: list[dict]
    stats: dict
    created_by: str


class StalenessOut(BaseModel):
    """Documents whose content changed after the snapshot was frozen."""

    status: str
    drifted_documents: list[str]


def _snapshot_out(record) -> SnapshotOut:
    return SnapshotOut(
        id=record.id,
        project_id=record.project_id,
        name=record.name,
        status=record.status,
        sources=record.sources,
        vector_profile=record.vector_profile,
        stats=record.stats,
        created_by=record.created_by,
    )


@router.post("/projects/{project_id}/snapshots", response_model=SnapshotOut, status_code=201)
async def create_snapshot(
    project_id: str, body: SnapshotIn, request: Request, user_id: str = Depends(current_user)
) -> SnapshotOut:
    """Freeze the selected documents. Unfinished documents are listed, not included.

    The same sources can be submitted again: segments already stored for an
    origin chunk are kept, so a retry does not duplicate the corpus.
    """
    await _projects(request).require_role(project_id, user_id, "editor")
    repo = _snapshots(request)
    record = await repo.create(project_id, user_id, body.name, body.sources)
    try:
        draft = await SnapshotBuilder(_gateway(request, user_id)).build(record.id, body.sources)
        record = await repo.save_build(record.id, draft)
    except Exception as exc:
        await repo.mark_failed(record.id, str(exc))
        raise
    return _snapshot_out(record)


@router.get("/projects/{project_id}/snapshots", response_model=list[SnapshotOut])
async def list_snapshots(project_id: str, request: Request, user_id: str = Depends(current_user)) -> list[SnapshotOut]:
    """A project's snapshots. Viewers included."""
    await _projects(request).require_role(project_id, user_id, "viewer")
    return [_snapshot_out(record) for record in await _snapshots(request).list_for_project(project_id)]


@router.get("/projects/{project_id}/snapshots/{snapshot_id}", response_model=SnapshotOut)
async def get_snapshot(
    project_id: str, snapshot_id: str, request: Request, user_id: str = Depends(current_user)
) -> SnapshotOut:
    """One snapshot."""
    await _projects(request).require_role(project_id, user_id, "viewer")
    return _snapshot_out(await _snapshots(request).require_project(snapshot_id, project_id))


@router.get("/projects/{project_id}/snapshots/{snapshot_id}/segments", response_model=list[Segment])
async def snapshot_segments(
    project_id: str,
    snapshot_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=1000),
    after: str | None = None,
    user_id: str = Depends(current_user),
) -> list[Segment]:
    """One cursor page of frozen segments, ordered by platform id."""
    await _projects(request).require_role(project_id, user_id, "viewer")
    await _snapshots(request).require_project(snapshot_id, project_id)
    return await _snapshots(request).segments(snapshot_id, limit, after)


@router.get("/projects/{project_id}/snapshots/{snapshot_id}/health", response_model=HealthReport)
async def snapshot_health(
    project_id: str, snapshot_id: str, request: Request, user_id: str = Depends(current_user)
) -> HealthReport:
    """The corpus check. Problems are fixed in RAGFlow, then a new snapshot is taken."""
    await _projects(request).require_role(project_id, user_id, "viewer")
    await _snapshots(request).require_project(snapshot_id, project_id)
    return await _snapshots(request).health(snapshot_id)


@router.post("/projects/{project_id}/snapshots/{snapshot_id}:check-staleness", response_model=StalenessOut)
async def check_staleness(
    project_id: str, snapshot_id: str, request: Request, user_id: str = Depends(current_user)
) -> StalenessOut:
    """Compare frozen document hashes with RAGFlow. Drift marks the snapshot stale.

    A stale snapshot is never updated in place. The caller creates a new one.
    """
    await _projects(request).require_role(project_id, user_id, "viewer")
    repo = _snapshots(request)
    await repo.require_project(snapshot_id, project_id)
    frozen = await repo.documents(snapshot_id)
    gateway = _gateway(request, user_id)
    current = []
    for kb_id in {document.kb_id for document in frozen}:
        cursor = None
        while True:
            page = await gateway.list_documents(kb_id, cursor)
            current.extend(page.documents)
            if not page.next_cursor:
                break
            cursor = page.next_cursor
    drifted = drifted_documents(frozen, current)
    record = await repo.mark_stale(snapshot_id, drifted)
    return StalenessOut(status=record.status, drifted_documents=drifted)


@router.get("/ragflow/models", response_model=list[Model])
async def ragflow_models(request: Request, types: str = "", user_id: str = Depends(current_user)) -> list[Model]:
    """Models the caller may use in RAGFlow. No credentials are returned."""
    wanted = [item for item in types.split(",") if item]
    return await _gateway(request, user_id).list_models(wanted or None)


class RecipeIn(BaseModel):
    """A recipe draft."""

    name: str
    config: dict


class RunIn(BaseModel):
    """A request to run a recipe against a snapshot."""

    recipe_id: str
    snapshot_id: str
    limit: int = Field(default=20, ge=1, le=500_000)
    recipe_version_id: str | None = None


class PreviewIn(BaseModel):
    snapshot_id: str
    limit: int = Field(default=10, ge=1, le=50)


class ReleaseIn(BaseModel):
    warning_reason: str = Field(default="", max_length=2000)


class BudgetIn(BaseModel):
    max_tokens: int = Field(ge=1, lt=2**31)
    max_invocations: int = Field(ge=1, lt=2**31)
    reason: str = Field(min_length=1, max_length=2000)


class ReconcileIn(BaseModel):
    actual_tokens: int = Field(ge=0, lt=2**31)
    reason: str = Field(min_length=1, max_length=2000)


@router.put("/projects/{project_id}/runs/{run_id}/budget", response_model=RunRecord)
async def adjust_run_budget(
    project_id: str, run_id: str, body: BudgetIn, request: Request, user_id: str = Depends(current_user)
) -> RunRecord:
    from datafactory.engine.accounts import adjust_budget

    await adjust_budget(request.state.session, project_id, run_id, user_id, **body.model_dump())
    return await _production(request, user_id).get_run(project_id, run_id, user_id)


@router.post("/projects/{project_id}/runs/{run_id}/invocations/{invocation_id}:reconcile", response_model=RunRecord)
async def reconcile_invocation(
    project_id: str,
    run_id: str,
    invocation_id: str,
    body: ReconcileIn,
    request: Request,
    user_id: str = Depends(current_user),
) -> RunRecord:
    from datafactory.engine.accounts import reconcile

    await reconcile(request.state.session, project_id, run_id, invocation_id, user_id, **body.model_dump())
    return await _production(request, user_id).get_run(project_id, run_id, user_id)


class ReviewIn(BaseModel):
    """A human decision."""

    decision: str
    reason: str = ""


class ExportOut(BaseModel):
    adapter: str
    files: dict[str, str]
    issues: list[str]


def _recipes(request: Request) -> RecipeRepository:
    return RecipeRepository(request.state.session)


def _production(request: Request, user_id: str) -> ProductionService:
    return ProductionService(request.state.session, _gateway(request, user_id), request.app.state.objects)


@router.get("/projects/{project_id}/recipes", response_model=list[RecipeSummary])
async def list_recipes(project_id: str, request: Request, user_id: str = Depends(current_user)) -> list[RecipeSummary]:
    """A project's recipes."""
    return await _recipes(request).list_for(project_id, user_id)


@router.post("/projects/{project_id}/recipes", response_model=RecipeRecord, status_code=201)
async def create_recipe(
    project_id: str, body: RecipeIn, request: Request, user_id: str = Depends(current_user)
) -> RecipeRecord:
    """Validate and store a recipe draft."""
    return await _recipes(request).create(project_id, user_id, body.name, body.config)


@router.get("/projects/{project_id}/recipes/{recipe_id}", response_model=RecipeRecord)
async def get_recipe(
    project_id: str, recipe_id: str, request: Request, user_id: str = Depends(current_user)
) -> RecipeRecord:
    """One recipe with its draft config."""
    return await _recipes(request).get(project_id, recipe_id, user_id)


@router.post("/projects/{project_id}/recipes/{recipe_id}/versions")
async def publish_recipe_version(
    project_id: str, recipe_id: str, request: Request, user_id: str = Depends(current_user)
) -> dict:
    """Freeze the current draft as the next version."""
    return await _recipes(request).publish_version(project_id, recipe_id, user_id)


@router.post("/projects/{project_id}/runs", response_model=RunRecord, status_code=201)
async def start_run(project_id: str, body: RunIn, request: Request, user_id: str = Depends(current_user)) -> RunRecord:
    """Queue a run. The worker produces the dataset; poll the run for status."""
    return await _production(request, user_id).start_run(
        project_id,
        user_id,
        body.recipe_id,
        body.snapshot_id,
        body.limit,
        version_id=body.recipe_version_id,
        key=request.headers.get("Idempotency-Key", ""),
    )


@router.get("/projects/{project_id}/runs", response_model=list[RunRecord])
async def list_runs(project_id: str, request: Request, user_id: str = Depends(current_user)) -> list[RunRecord]:
    """A project's runs, newest first in the order they were stored."""
    return await _production(request, user_id).list_runs(project_id, user_id)


@router.get("/projects/{project_id}/runs/{run_id}", response_model=RunRecord)
async def get_run(project_id: str, run_id: str, request: Request, user_id: str = Depends(current_user)) -> RunRecord:
    """One run, including its error when it failed."""
    return await _production(request, user_id).get_run(project_id, run_id, user_id)


@router.get("/projects/{project_id}/runs/{run_id}/metrics", response_model=RunMetrics)
async def run_metrics(
    project_id: str,
    run_id: str,
    request: Request,
    after: str | None = None,
    user_id: str = Depends(current_user),
) -> RunMetrics:
    return await _production(request, user_id).metrics(project_id, run_id, user_id, after)


@router.get("/projects/{project_id}/runs/{run_id}/events")
async def run_events(project_id: str, run_id: str, request: Request, user_id: str = Depends(current_user)):
    from fastapi.responses import StreamingResponse

    from datafactory.app.events import run_stream

    await _production(request, user_id).get_run(project_id, run_id, user_id)
    return StreamingResponse(
        run_stream(request, project_id, run_id, user_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/projects/{project_id}/runs/{run_id}:cancel", response_model=RunRecord)
async def cancel_run(project_id: str, run_id: str, request: Request, user_id: str = Depends(current_user)) -> RunRecord:
    """Stop a queued or running run. Calls already sent to a model are not undone."""
    return await _production(request, user_id).control_run(project_id, run_id, user_id, "cancel")


@router.post("/projects/{project_id}/runs/{run_id}:pause", response_model=RunRecord)
async def pause_run(project_id: str, run_id: str, request: Request, user_id: str = Depends(current_user)) -> RunRecord:
    return await _production(request, user_id).control_run(project_id, run_id, user_id, "pause")


@router.post("/projects/{project_id}/runs/{run_id}:resume", response_model=RunRecord)
async def resume_run(project_id: str, run_id: str, request: Request, user_id: str = Depends(current_user)) -> RunRecord:
    return await _production(request, user_id).control_run(project_id, run_id, user_id, "resume")


@router.post("/projects/{project_id}/recipes/{recipe_id}:preview", response_model=RunRecord, status_code=202)
async def preview_recipe(
    project_id: str, recipe_id: str, body: PreviewIn, request: Request, user_id: str = Depends(current_user)
) -> RunRecord:
    """Queue a preview through the same versioned executor as a production run."""
    return await _production(request, user_id).start_run(
        project_id,
        user_id,
        recipe_id,
        body.snapshot_id,
        body.limit,
        mode="preview",
        key=request.headers.get("Idempotency-Key", ""),
    )


@router.get("/projects/{project_id}/overview", response_model=OverviewRecord)
async def overview(project_id: str, request: Request, user_id: str = Depends(current_user)) -> dict:
    """Counts for the project overview and the review badge."""
    return await _production(request, user_id).counts(project_id, user_id)


@router.get("/projects/{project_id}/datasets", response_model=list[DatasetRecord])
async def list_datasets(project_id: str, request: Request, user_id: str = Depends(current_user)) -> list[DatasetRecord]:
    """Datasets the project has produced."""
    return await _production(request, user_id).list_datasets(project_id, user_id)


@router.get("/projects/{project_id}/datasets/{dataset_id}/samples", response_model=list[SampleRecord])
async def dataset_samples(
    project_id: str, dataset_id: str, request: Request, split: str | None = None, user_id: str = Depends(current_user)
) -> list[SampleRecord]:
    """Samples in a dataset, optionally one split."""
    return await _production(request, user_id).samples(project_id, dataset_id, user_id, split)


@router.get("/projects/{project_id}/review-queue", response_model=list[SampleRecord])
async def review_queue(project_id: str, request: Request, user_id: str = Depends(current_user)) -> list[SampleRecord]:
    """Pending samples waiting for a reviewer."""
    return await _production(request, user_id).review_queue(project_id, user_id)


@router.post("/projects/{project_id}/samples/{sample_id}/reviews", response_model=SampleRecord)
async def review_sample(
    project_id: str, sample_id: str, body: ReviewIn, request: Request, user_id: str = Depends(current_user)
) -> SampleRecord:
    """Record a reviewer's decision. The sample body is not changed."""
    return await _production(request, user_id).review(project_id, sample_id, user_id, body.decision, body.reason)


@router.post("/projects/{project_id}/datasets/{dataset_id}/releases", response_model=ReleaseRecord, status_code=201)
async def create_release(
    project_id: str,
    dataset_id: str,
    request: Request,
    body: ReleaseIn | None = None,
    user_id: str = Depends(current_user),
) -> ReleaseRecord:
    """Freeze the approved samples. Blockers leave the release blocked."""
    return await _production(request, user_id).release(
        project_id, dataset_id, user_id, body.warning_reason if body else ""
    )


@router.get("/projects/{project_id}/releases", response_model=list[ReleaseRecord])
async def list_releases(project_id: str, request: Request, user_id: str = Depends(current_user)) -> list[ReleaseRecord]:
    """Releases of the project's datasets."""
    return await _production(request, user_id).list_releases(project_id, user_id)


@router.post("/projects/{project_id}/releases/{release_id}:export", response_model=ExportOut)
async def export_release(
    project_id: str, release_id: str, request: Request, adapter: str = "canonical", user_id: str = Depends(current_user)
) -> dict:
    """Render a release through one adapter and return the files as text."""
    return await _production(request, user_id).export(project_id, release_id, user_id, adapter)


@router.get("/projects/{project_id}/releases/{release_id}", response_model=ReleaseRecord)
async def get_release(
    project_id: str, release_id: str, request: Request, user_id: str = Depends(current_user)
) -> ReleaseRecord:
    """One release with its gate results."""
    return await _production(request, user_id).get_release(project_id, release_id, user_id)


@router.get("/projects/{project_id}/releases/{release_id}/package")
async def download_release(
    project_id: str, release_id: str, request: Request, adapter: str = "canonical", user_id: str = Depends(current_user)
) -> Response:
    data = await _production(request, user_id).export_package(project_id, release_id, user_id, adapter)
    return Response(
        data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{release_id}-{adapter}.zip"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
