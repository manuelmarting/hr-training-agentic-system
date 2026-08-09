"""Studio API (plan §5).

Covers the whole human-review loop over drafts — create (empty, seeded from the committed
graph, or built by LLM extraction over uploaded SOPs), edit nodes/edges, validate, and the
server-enforced Approve that materializes YAML. The Approve gate re-runs full validation
server-side and refuses (422) on any blocking item, so a KC without reviewed provenance can
never reach a runtime graph — the whole point of the workflow (plan §1).

Extraction is a background task (8+ LLM calls) with progress streamed over SSE (plan §4/§5)
so the request never blocks on the whole corpus pass.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.agent.llm import StructuredLLMError, get_structured_llm
from app.config import settings
from app.studio.extract import ExtractionEvent, extract_graph
from app.studio.ingest import IngestedDoc, UnsupportedDocumentError, ingest
from app.studio.materialize import (
    draft_from_graph_yaml,
    materialize_to_yaml,
    write_graph,
)
from app.studio.reconcile import load_seed_ids
from app.studio.repo import DraftNotFoundError, DraftRepo
from app.studio.schemas import (
    Domain,
    DraftStatus,
    GraphDraft,
    ProposedEdge,
    ProposedKC,
    Provenance,
)
from app.studio.validate import ValidationResult, validate_draft

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio", tags=["studio"])

SEED_GRAPH = Path(__file__).resolve().parents[1] / "kg" / "graph.yaml"
SOPS_DIR = Path(__file__).resolve().parents[3] / "docs" / "sops"

# In-process progress channels for running extractions: draft_id -> event queue.
# A `None` sentinel on the queue marks the end of the stream.
_extraction_queues: dict[str, asyncio.Queue[ExtractionEvent | None]] = {}


# Repo wiring ---------------------------------------------------------------

_repo: DraftRepo | None = None


def get_repo() -> DraftRepo:
    """Process-wide draft repo. Overridden in tests via `dependency_overrides`."""
    global _repo
    if _repo is None:
        _repo = DraftRepo(settings.studio_db_path)
    return _repo


# Request models ------------------------------------------------------------


class AddKCRequest(BaseModel):
    id: str
    name: str
    domain: Domain
    description: str = ""
    regulation: str | None = None
    known_misconceptions: list[str] = []
    superseded_by_kc_id: str | None = None
    provenance: Provenance


class PatchKCRequest(BaseModel):
    name: str | None = None
    domain: Domain | None = None
    description: str | None = None
    regulation: str | None = None
    known_misconceptions: list[str] | None = None
    superseded_by_kc_id: str | None = None
    provenance: Provenance | None = None


class AddEdgeRequest(BaseModel):
    source_kc_id: str
    target_kc_id: str
    rationale: str = ""
    provenance: Provenance | None = None


class ApproveResponse(BaseModel):
    draft_id: str
    status: DraftStatus
    path: str
    yaml: str


# Routes --------------------------------------------------------------------


@router.post("/drafts", response_model=GraphDraft)
async def create_draft(
    files: list[UploadFile] = File(default=[]),
    role: str = Form("warehouse_operative"),
    seed_from_graph: bool = Form(False),
    repo: DraftRepo = Depends(get_repo),
) -> GraphDraft:
    """Create a draft. `seed_from_graph` opens the committed graph for re-review;
    otherwise the draft is empty and authored by hand. Extraction is deferred."""
    draft_id = uuid.uuid4().hex
    source_docs = [f.filename for f in files if f.filename]

    def _create() -> GraphDraft:
        if seed_from_graph:
            draft = draft_from_graph_yaml(SEED_GRAPH, draft_id=draft_id)
            draft.role = role
            if source_docs:
                draft.source_docs = source_docs
        else:
            draft = GraphDraft(draft_id=draft_id, role=role, source_docs=source_docs)
        return repo.create(draft)

    return await asyncio.to_thread(_create)


@router.get("/drafts", response_model=list[GraphDraft])
async def list_drafts(repo: DraftRepo = Depends(get_repo)) -> list[GraphDraft]:
    return await asyncio.to_thread(repo.list_drafts)


@router.get("/drafts/{draft_id}", response_model=GraphDraft)
async def get_draft(draft_id: str, repo: DraftRepo = Depends(get_repo)) -> GraphDraft:
    return await asyncio.to_thread(_get_or_404, repo, draft_id)


@router.get("/drafts/{draft_id}/validation", response_model=ValidationResult)
async def get_validation(draft_id: str, repo: DraftRepo = Depends(get_repo)) -> ValidationResult:
    draft = await asyncio.to_thread(_get_or_404, repo, draft_id)
    return validate_draft(draft)


@router.post("/drafts/{draft_id}/kcs", response_model=GraphDraft)
async def add_kc(
    draft_id: str, body: AddKCRequest, repo: DraftRepo = Depends(get_repo)
) -> GraphDraft:
    def _add() -> GraphDraft:
        draft = _get_or_404(repo, draft_id)
        if any(kc.id == body.id for kc in draft.kcs):
            raise HTTPException(status_code=409, detail=f"KC id '{body.id}' already exists")
        draft.kcs.append(ProposedKC(**body.model_dump(), origin="manual"))
        return repo.save(draft)

    return await asyncio.to_thread(_add)


@router.patch("/drafts/{draft_id}/kcs/{kc_id}", response_model=GraphDraft)
async def patch_kc(
    draft_id: str,
    kc_id: str,
    body: PatchKCRequest,
    repo: DraftRepo = Depends(get_repo),
) -> GraphDraft:
    def _patch() -> GraphDraft:
        draft = _get_or_404(repo, draft_id)
        kc = _find_kc(draft, kc_id)
        updates = body.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(kc, field, value)
        kc.origin = "edited"  # a human touched this node — the visible HITL evidence
        return repo.save(draft)

    return await asyncio.to_thread(_patch)


@router.delete("/drafts/{draft_id}/kcs/{kc_id}", response_model=GraphDraft)
async def delete_kc(draft_id: str, kc_id: str, repo: DraftRepo = Depends(get_repo)) -> GraphDraft:
    def _delete() -> GraphDraft:
        draft = _get_or_404(repo, draft_id)
        _find_kc(draft, kc_id)  # 404 if absent
        draft.kcs = [kc for kc in draft.kcs if kc.id != kc_id]
        draft.edges = [e for e in draft.edges if kc_id not in (e.source_kc_id, e.target_kc_id)]
        return repo.save(draft)

    return await asyncio.to_thread(_delete)


@router.post("/drafts/{draft_id}/edges", response_model=GraphDraft)
async def add_edge(
    draft_id: str, body: AddEdgeRequest, repo: DraftRepo = Depends(get_repo)
) -> GraphDraft:
    def _add() -> GraphDraft:
        draft = _get_or_404(repo, draft_id)
        exists = any(
            e.source_kc_id == body.source_kc_id and e.target_kc_id == body.target_kc_id
            for e in draft.edges
        )
        if not exists:
            draft.edges.append(ProposedEdge(**body.model_dump(), origin="manual"))
        return repo.save(draft)

    return await asyncio.to_thread(_add)


@router.delete("/drafts/{draft_id}/edges", response_model=GraphDraft)
async def delete_edge(
    draft_id: str,
    source_kc_id: str,
    target_kc_id: str,
    repo: DraftRepo = Depends(get_repo),
) -> GraphDraft:
    def _delete() -> GraphDraft:
        draft = _get_or_404(repo, draft_id)
        draft.edges = [
            e
            for e in draft.edges
            if not (e.source_kc_id == source_kc_id and e.target_kc_id == target_kc_id)
        ]
        return repo.save(draft)

    return await asyncio.to_thread(_delete)


@router.get("/drafts/{draft_id}/yaml")
async def preview_yaml(draft_id: str, repo: DraftRepo = Depends(get_repo)) -> dict[str, str]:
    draft = await asyncio.to_thread(_get_or_404, repo, draft_id)
    return {"yaml": materialize_to_yaml(draft)}


@router.post("/drafts/{draft_id}/approve", response_model=ApproveResponse)
async def approve_draft(draft_id: str, repo: DraftRepo = Depends(get_repo)) -> ApproveResponse:
    """Validate server-side, then materialize. Rejects (422) on any blocking item —
    a client-side-only gate would defeat the entire workflow (plan §5)."""
    draft = await asyncio.to_thread(_get_or_404, repo, draft_id)

    result = validate_draft(draft)
    if not result.ok:
        raise HTTPException(status_code=422, detail=result.model_dump())

    def _materialize() -> tuple[Path, str]:
        out_dir = settings.graph_output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{draft.role}-{draft.draft_id}.yaml"
        write_graph(draft, path)
        repo.set_status(draft.draft_id, DraftStatus.APPROVED)
        return path, materialize_to_yaml(draft)

    path, yaml_text = await asyncio.to_thread(_materialize)
    return ApproveResponse(
        draft_id=draft.draft_id,
        status=DraftStatus.APPROVED,
        path=str(path),
        yaml=yaml_text,
    )


# Extraction from SOPs (plan §4/§5) -----------------------------------------


class SopDoc(BaseModel):
    doc_id: str
    filename: str
    chars: int


@router.get("/sops", response_model=list[SopDoc])
async def list_sops() -> list[SopDoc]:
    """The committed SOP corpus, offered pre-selected in the studio's uploader."""

    def _read() -> list[SopDoc]:
        docs: list[SopDoc] = []
        for path in sorted(SOPS_DIR.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            docs.append(
                SopDoc(
                    doc_id=path.stem,
                    filename=path.name,
                    chars=len(path.read_text(encoding="utf-8")),
                )
            )
        return docs

    return await asyncio.to_thread(_read)


@router.post("/drafts/extract", response_model=GraphDraft)
async def create_draft_from_sops(
    files: list[UploadFile] = File(default=[]),
    role: str = Form("warehouse_operative"),
    sop_ids: str = Form(""),
    repo: DraftRepo = Depends(get_repo),
) -> GraphDraft:
    """Create a draft by LLM extraction over selected committed SOPs + uploaded files.

    Returns immediately with a draft in `extracting` status; progress streams over
    `GET /drafts/{id}/events`. Documents are read/ingested here (before the request ends,
    while the uploads are still valid) and handed to the background task.
    """
    docs: list[IngestedDoc] = []

    for sop_id in (s.strip() for s in sop_ids.split(",")):
        if not sop_id:
            continue
        path = SOPS_DIR / f"{sop_id}.md"
        if path.exists():
            docs.append(ingest(path.name, await asyncio.to_thread(path.read_bytes)))

    for upload in files:
        if not upload.filename:
            continue
        raw = await upload.read()
        try:
            docs.append(ingest(upload.filename, raw))
        except UnsupportedDocumentError as error:
            logger.warning("skipping unsupported upload %s: %s", upload.filename, error)

    if not docs:
        raise HTTPException(status_code=400, detail="no readable documents provided")

    draft_id = uuid.uuid4().hex
    draft = GraphDraft(
        draft_id=draft_id,
        role=role,
        status=DraftStatus.EXTRACTING,
        source_docs=[doc.doc_id for doc in docs],
    )
    await asyncio.to_thread(repo.create, draft)

    _extraction_queues[draft_id] = asyncio.Queue()
    asyncio.create_task(_run_extraction(repo, draft_id, docs, role))
    return draft


@router.get("/drafts/{draft_id}/events")
async def extraction_events(draft_id: str) -> EventSourceResponse:
    """Stream extraction progress for a draft (SSE). Emits `progress` events then `end`."""
    queue = _extraction_queues.get(draft_id)

    async def stream() -> AsyncIterator[dict]:
        if queue is None:
            yield {"event": "end", "data": ""}
            return
        try:
            while True:
                event = await queue.get()
                if event is None:
                    yield {"event": "end", "data": ""}
                    return
                yield {"event": "progress", "data": event.model_dump_json()}
        finally:
            _extraction_queues.pop(draft_id, None)

    return EventSourceResponse(stream())


async def _run_extraction(
    repo: DraftRepo, draft_id: str, docs: list[IngestedDoc], role: str
) -> None:
    """Background: run the two-pass extraction, persist the draft, stream progress."""
    queue = _extraction_queues[draft_id]

    async def emit(event: ExtractionEvent) -> None:
        await queue.put(event)

    try:
        llm = get_structured_llm()  # raises StructuredLLMError if no API key
        seed_ids = await asyncio.to_thread(load_seed_ids, SEED_GRAPH)
        draft = await extract_graph(
            llm, docs, role=role, draft_id=draft_id, seed_ids=seed_ids, progress=emit
        )
        result = validate_draft(draft)
        await asyncio.to_thread(repo.save, draft)
        await emit(
            ExtractionEvent(
                type="validated",
                kc_count=len(draft.kcs),
                edge_count=len(draft.edges),
                detail=f"{len(result.issues)} blocking issue(s)",
            )
        )
        await emit(
            ExtractionEvent(type="done", kc_count=len(draft.kcs), edge_count=len(draft.edges))
        )
    except StructuredLLMError as error:
        logger.warning("extraction for %s failed: %s", draft_id, error)
        await asyncio.to_thread(repo.set_status, draft_id, DraftStatus.FAILED)
        await emit(ExtractionEvent(type="failed", detail=str(error)))
    except Exception as error:  # noqa: BLE001 - background task must never crash silently
        logger.exception("unexpected extraction failure for %s", draft_id)
        await asyncio.to_thread(repo.set_status, draft_id, DraftStatus.FAILED)
        await emit(ExtractionEvent(type="failed", detail=str(error)))
    finally:
        await queue.put(None)


# Helpers -------------------------------------------------------------------


def _get_or_404(repo: DraftRepo, draft_id: str) -> GraphDraft:
    try:
        return repo.get(draft_id)
    except DraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"draft '{draft_id}' not found") from exc


def _find_kc(draft: GraphDraft, kc_id: str) -> ProposedKC:
    for kc in draft.kcs:
        if kc.id == kc_id:
            return kc
    raise HTTPException(status_code=404, detail=f"KC '{kc_id}' not found in draft")
