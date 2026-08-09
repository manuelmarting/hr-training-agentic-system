"""Two-pass LLM extraction (plan §4): per-document KCs, then corpus-level edges.

Pass A proposes KCs one document at a time (concurrent, bounded). `reconcile` dedupes and
assigns ids. Pass B, given the whole reconciled KC list plus the corpus, proposes the
prerequisite edges — including the cross-document ones a single-document pass can't see.

Every LLM call goes through the shared `StructuredLLM.extract` (repair-once), and each pass
degrades to a safe fallback on failure (an empty KC list for a failed document, no edges for
a failed corpus pass) rather than raising — a partial graph is reviewable; a crash is not.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel

from app.agent.llm import StructuredLLM, StructuredLLMError
from app.config import settings
from app.studio.extract_schemas import DocKCProposal, EdgeProposal
from app.studio.ingest import IngestedDoc
from app.studio.reconcile import reconcile
from app.studio.schemas import GraphDraft, ProposedEdge, ProposedKC

logger = logging.getLogger(__name__)


class ExtractionEvent(BaseModel):
    """A progress update streamed to the studio UI during a background extraction run."""

    type: Literal[
        "doc_started",
        "doc_done",
        "reconciled",
        "edges_started",
        "edges_done",
        "validated",
        "done",
        "failed",
    ]
    doc_id: str | None = None
    detail: str | None = None
    kc_count: int | None = None
    edge_count: int | None = None


ProgressHook = Callable[[ExtractionEvent], Awaitable[None]]


async def _emit(progress: ProgressHook | None, event: ExtractionEvent) -> None:
    if progress is not None:
        await progress(event)


_SYSTEM_A = (
    "You are a curriculum architect building a knowledge graph for workplace training. "
    "Given one standard operating procedure (SOP), propose the discrete knowledge "
    "components (KCs) a worker must hold to perform it safely and correctly. For each KC "
    "give a short name, its domain (safety, equipment, process, systems, or behavioural), "
    "a one-sentence description, any regulation it is mandated by, known worker "
    "misconceptions the SOP calls out, the nearest section heading, and a short verbatim "
    "excerpt the KC is drawn from. Propose only what this document supports."
)

_SYSTEM_B = (
    "You are a curriculum architect determining prerequisite relationships between "
    "knowledge components (KCs). Given the full KC list and the source documents, decide "
    "which KCs must be MASTERED BEFORE others can be assessed. A prerequisite edge goes "
    "source -> target, meaning source must be mastered first. Base every edge on the "
    "text — especially cross-references where one document relies on a rule defined in "
    "another. Reference KCs only by the ids given. Do not invent ids. Only propose edges "
    "with clear textual support."
)


def _user_a(doc: IngestedDoc) -> str:
    return f'<sop id="{doc.doc_id}">\n{doc.text}\n</sop>'


def _user_b(kcs: list[ProposedKC], docs: list[IngestedDoc]) -> str:
    kc_lines = "\n".join(
        f"{kc.id} | {kc.name} | {kc.domain} | from {kc.provenance.doc_id}" for kc in kcs
    )
    corpus = "\n\n".join(f'<sop id="{d.doc_id}">\n{d.text}\n</sop>' for d in docs)
    return f"KNOWLEDGE COMPONENTS:\n{kc_lines}\n\nSOURCE DOCUMENTS:\n{corpus}"


async def _propose_doc(
    llm: StructuredLLM,
    doc: IngestedDoc,
    sem: asyncio.Semaphore,
    progress: ProgressHook | None,
) -> tuple[str, DocKCProposal]:
    async with sem:
        await _emit(progress, ExtractionEvent(type="doc_started", doc_id=doc.doc_id))
        try:
            proposal = await llm.extract(DocKCProposal, _SYSTEM_A, _user_a(doc))
        except StructuredLLMError as error:
            logger.warning("pass A failed for %s, skipping document: %s", doc.doc_id, error)
            await _emit(
                progress,
                ExtractionEvent(type="doc_done", doc_id=doc.doc_id, detail=f"failed: {error}"),
            )
            return doc.doc_id, DocKCProposal()
        await _emit(
            progress,
            ExtractionEvent(type="doc_done", doc_id=doc.doc_id, kc_count=len(proposal.kcs)),
        )
        return doc.doc_id, proposal


async def _propose_edges(
    llm: StructuredLLM,
    kcs: list[ProposedKC],
    docs: list[IngestedDoc],
    progress: ProgressHook | None,
) -> list[ProposedEdge]:
    if len(kcs) < 2:
        return []
    await _emit(progress, ExtractionEvent(type="edges_started"))
    try:
        proposal = await llm.extract(EdgeProposal, _SYSTEM_B, _user_b(kcs, docs))
    except StructuredLLMError as error:
        logger.warning("pass B (edges) failed, materializing without edges: %s", error)
        return []

    known = {kc.id for kc in kcs}
    edges: list[ProposedEdge] = []
    seen: set[tuple[str, str]] = set()
    for edge in proposal.edges:
        pair = (edge.source_kc_id, edge.target_kc_id)
        if edge.source_kc_id not in known or edge.target_kc_id not in known:
            continue  # drop hallucinated endpoints; validation would flag them anyway
        if edge.source_kc_id == edge.target_kc_id or pair in seen:
            continue
        seen.add(pair)
        edges.append(
            ProposedEdge(
                source_kc_id=edge.source_kc_id,
                target_kc_id=edge.target_kc_id,
                rationale=edge.rationale,
                origin="extracted",
            )
        )
    await _emit(progress, ExtractionEvent(type="edges_done", edge_count=len(edges)))
    return edges


async def extract_graph(
    llm: StructuredLLM,
    docs: list[IngestedDoc],
    *,
    role: str = "warehouse_operative",
    draft_id: str | None = None,
    seed_ids: dict[str, str] | None = None,
    max_concurrency: int | None = None,
    progress: ProgressHook | None = None,
) -> GraphDraft:
    """Run pass A (concurrent) → reconcile → pass B, returning a reviewable draft."""
    sem = asyncio.Semaphore(max_concurrency or settings.extraction_max_concurrency)
    results = await asyncio.gather(*(_propose_doc(llm, doc, sem, progress) for doc in docs))
    proposals = {doc_id: proposal.kcs for doc_id, proposal in results}

    kcs = reconcile(proposals, seed_ids or {})
    await _emit(progress, ExtractionEvent(type="reconciled", kc_count=len(kcs)))
    edges = await _propose_edges(llm, kcs, docs, progress)

    return GraphDraft(
        draft_id=draft_id or uuid.uuid4().hex,
        role=role,
        status="draft",
        source_docs=[doc.doc_id for doc in docs],
        kcs=kcs,
        edges=edges,
    )
