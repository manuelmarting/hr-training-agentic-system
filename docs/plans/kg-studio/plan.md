# Plan — Workflow 2: Knowledge-Graph Authoring Studio

**Scope:** PRD §8 (+ §8.5 demo beat). An employer uploads SOPs, an LLM proposes a KC taxonomy and `prerequisite_of` edges, a human reviews node-by-node against source excerpts, and only an explicit **Approve** materializes the YAML that [workflow 1](../conversational-agent/plan.md) loads.

**The point of this workflow** (PRD §8.4): it's the fail-closed posture of the PII gate applied to graph authorship. Nothing self-materializes. The interesting failure mode is *"a plausible-looking KC reaches a live assessment without a human ever having seen its source paragraph"* — the design must make that impossible.

**Status:** phases 1–5 done. Built: `studio/{schemas,validate,repo,materialize,ingest,reconcile,extract,extract_schemas}.py`, `agent/llm.py` (shared `StructuredLLM` protocol + repair wrapper, shared with [workflow 1](../conversational-agent/plan.md)), `kg/{loader.py,graph.yaml}`, `api/studio.py` (incl. `GET /sops`, `POST /drafts/extract`, and the `GET /drafts/{id}/events` SSE progress stream), and the full `frontend/src/studio/` route (canvas, node/provenance editor, edge editor, approve gate, **"Seed from SOPs" uploader + live extraction progress**). Extraction runs as a background task streaming progress over SSE. **Diverged from this plan's original wording:** extraction is not hardcoded to `langchain-anthropic`/`claude-opus-4-8` — `api/studio.py:377` calls `get_structured_llm()` (`app/agent/llm.py`), which resolves whichever provider `settings.llm_provider` names (Gemini by default, Anthropic or OpenAI as alternates — same multi-provider boundary workflow 1 uses). It uses **seed-id reuse** so re-deriving the corpus reproduces the seed ids (§8.5). The whole upload → extract → review → approve → materialize loop is wired and verified against a live server (extraction resolves to `failed` without a configured provider key). Pending: the **live corpus run** (needs an API key for the configured provider) and the scripted §8.5 demo beat.

> **Corpus note:** `sops/README.md` and VISION §6.2 both say "24 KCs" but *enumerate 25* distinct ids (SAF 8 · EQP 5 · PRC 8 · SYS 2 · BEH 2). The "24" is a persistent miscount; the enumeration is authoritative, so the seed `kg/graph.yaml` carries all 25. Drop a node in the studio if 24 was intended.

---

## 1. Design commitments

| Decision | Choice | Why |
|---|---|---|
| Placement | A second route (`/studio`) in the existing Vite app | PRD §8.2: "not a separate app" |
| Draft storage | SQLite table `graph_drafts`, one row per draft, JSON blob | Drafts are edited wholesale by a single reviewer; no concurrency to model |
| Extraction | Two-pass LLM: per-document KC proposal, then a corpus-level edge pass | The four cross-document edges (`EQP.002→SAF.005`, `PRC.003→EQP.005`, `PRC.005→SAF.001`, `SYS.002→SYS.001/PRC.008`) are *unfindable* in a single-document pass — see [`docs/sops/README.md`](../../sops/README.md) |
| Extraction runtime | Background task, progress streamed over SSE | A corpus pass is 8+ LLM calls; the UI must not hang on a single request |
| Materialization | Writes a versioned YAML file + flips draft status to `approved` | The runtime graph file is only ever replaced by an approved draft |
| Graph rendering | Hand-rolled SVG layered DAG layout, no graph library | 24 nodes, one predicate. A force-directed lib is a dependency and worse UX than a topological layering |

**Invariant:** a KC without a `provenance` pointer (doc id + excerpt) cannot be approved. Validation rejects it. The reviewer is always reviewing a claim against its source.

---

## 2. Module layout

```
backend/app/studio/
  schemas.py         # ProposedKC, ProposedEdge, GraphDraft, Provenance, DraftStatus
  extract_schemas.py # DocKCProposal, EdgeProposal — the LLM-facing extraction output shapes
  ingest.py          # upload handling, text extraction (md/txt direct; PDF via pypdf)
  extract.py         # pass A: per-doc KC proposal; pass B: corpus-level edges (takes an injected StructuredLLM)
  reconcile.py       # dedupe near-identical KCs across docs, id assignment
  validate.py        # cycle detection, orphan/dangling edges, provenance required
  materialize.py     # approved draft -> kg/graph.yaml (same shape loader.py reads)
  repo.py            # draft CRUD on SQLite
backend/app/api/
  studio.py          # /api/studio/* routes; resolves the LLM via app/agent/llm.py::get_structured_llm()
frontend/src/studio/
  StudioPage.tsx       # route shell: upload -> extract -> review -> approve
  SopUploader.tsx       # named UploadPanel in the original sketch; same responsibility
  ExtractionProgress.tsx
  GraphCanvas.tsx      # SVG layered DAG; click selects a node
  NodeEditor.tsx       # attribute editing + provenance excerpt side by side
  EdgeEditor.tsx       # add / remove / redirect prerequisite_of
  ApproveBar.tsx       # validation summary + the Approve gate
  api.ts
```

New dependency: `pypdf` (PDF text extraction) — nothing else. The corpus is markdown, so PDF support is the only genuinely new capability.

---

## 3. Data model

```python
class Provenance(BaseModel):
    doc_id: str            # e.g. "06-picking-packing-dg-coldchain"
    heading: str           # nearest section heading
    excerpt: str           # verbatim span the KC was extracted from

class ProposedKC(BaseModel):
    id: str                # DOMAIN.NNN, assigned by reconcile.py
    name: str
    domain: Literal["safety", "equipment", "process", "systems", "behavioural"]
    description: str
    regulation: str | None = None
    known_misconceptions: list[str] = []
    superseded_by_kc_id: str | None = None
    provenance: Provenance            # required — no bare assertions
    origin: Literal["extracted", "edited", "manual"]

class ProposedEdge(BaseModel):
    source_kc_id: str      # prerequisite_of: source is required before target
    target_kc_id: str
    rationale: str
    provenance: Provenance | None     # None only for manually added edges
    origin: Literal["extracted", "edited", "manual"]

class GraphDraft(BaseModel):
    draft_id: str
    role: str = "warehouse_operative"
    status: Literal["extracting", "draft", "approved", "failed"]
    source_docs: list[str]
    kcs: list[ProposedKC]
    edges: list[ProposedEdge]
```

`origin` matters for the demo: the review UI must visibly mark which nodes the human touched, because that's the evidence the human-in-the-loop step is real.

---

## 4. Extraction pipeline

**Pass A — per document.** One structured-output call per SOP: "propose the knowledge components this document requires a worker to hold." Returns `ProposedKC[]` with provenance excerpts. Runs concurrently across docs (`asyncio.gather`, bounded).

**Reconcile.** Near-duplicate KCs proposed by two documents are merged (normalized-name similarity); ids assigned per domain in document order so the output is deterministic given the same proposals.

**Pass B — corpus level.** One call given the *full reconciled KC list plus every cross-reference sentence* found in the corpus: "which KCs must be mastered before which others, and on what textual basis?" This is where the four cross-document edges come from.

**Validate.** Cycle detection (`networkx.is_directed_acyclic_graph`), dangling edge endpoints, missing provenance, unknown domain. Failures are surfaced as blocking items in the UI, not exceptions.

Each pass uses the same repair-once-then-fallback wrapper as workflow 1 (`agent/llm.py`) — do not fork that logic.

---

## 5. API surface

| Endpoint | Purpose |
|---|---|
| `POST /api/studio/drafts` | Create an empty draft, or (`seed_from_graph: true`) seed one from the already-approved `kg/graph.yaml` for re-review |
| `POST /api/studio/drafts/extract` (multipart) | Upload docs and kick off extraction on a **new** draft — the create + extract step is two endpoints, not one |
| `GET /api/studio/drafts` | List all drafts |
| `GET /api/studio/drafts/{id}` | Full draft for the review UI |
| `GET /api/studio/drafts/{id}/events` (SSE) | Extraction progress: `doc_started`, `doc_done`, `edges_done`, `validated`, `failed` |
| `GET /api/studio/drafts/{id}/validation` | Validation-only check, independent of fetching the whole draft |
| `POST /api/studio/drafts/{id}/kcs` | Add a KC manually |
| `PATCH /api/studio/drafts/{id}/kcs/{kc_id}` | Edit attributes (sets `origin: edited`) |
| `DELETE /api/studio/drafts/{id}/kcs/{kc_id}` | Delete a KC; cascades to remove edges touching it |
| `POST` / `DELETE /api/studio/drafts/{id}/edges` | Add / remove edges — there is no atomic "redirect"; the UI does delete+add |
| `POST /api/studio/drafts/{id}/approve` | Validate → materialize YAML → status `approved` |
| `GET /api/studio/drafts/{id}/yaml` | Preview the materialized YAML (used in the demo beat) |
| `GET /api/studio/sops` | List the committed SOP corpus, for pre-selection in the uploader |

`approve` re-runs full validation server-side and **rejects** on any blocking item. A client-side-only gate would defeat the entire point of the workflow.

---

## 6. Review UI behavior

- **Layout:** graph canvas left/center, editor panel right. Selecting a node shows its attributes *and* its provenance excerpt in the same view — never one without the other.
- **Layering:** topological levels left→right, so prerequisite direction is visually unambiguous. Color by domain (5 domains, reuse the mastery-panel palette from [workflow 3](../chat-ui/plan.md)).
- **Edit affordances:** rename, change domain, set `regulation` / `known_misconceptions` / `superseded_by_kc_id`, delete node, add node manually, drag-to-create or redirect an edge, delete an edge.
- **Validation surface:** a persistent banner listing blocking issues (cycle, dangling edge, missing provenance) with click-to-focus. Approve is disabled while any blocker stands.
- **Approve:** an explicit destructive-ish confirmation showing a diff-style summary — N KCs, M edges, K human edits — then the resulting YAML.

---

## 7. Build phases

1. **Schemas + repo + validation** (`schemas.py`, `repo.py`, `validate.py`) with unit tests for cycle detection, dangling edges, missing provenance. No LLM, no UI.
2. **Materialization**: `materialize.py` + a round-trip test — take the committed `kg/graph.yaml`, load it as a draft, materialize it back, assert byte-shape equivalence. This proves the studio's output is exactly what the runtime loads.
3. **Extraction** passes A/B with stubbed-LLM contract tests, then a live run over the real corpus.
4. **API routes** including the SSE progress stream.
5. **Studio UI**: upload → progress → canvas → editor → approve.
6. **Demo beat §8.5**: re-run on `01-ppe-manual-handling.md` and `06-picking-packing-dg-coldchain.md`, verify `SAF.001–004` / `PRC.003–006` re-derive, then deliberately edit one node name and redirect `PRC.005 → SAF.001`, approve, show the YAML is structurally identical to the seed graph.

Phases 1–2 are the ones that must not be cut: they are what makes the claim "the seed graph *is* an output of this pipeline" checkable rather than rhetorical.

---

## 8. Tests

| Area | Tests |
|---|---|
| Validation | cycle rejected, dangling edge rejected, provenance-less KC rejected, valid graph passes |
| Materialization | seed-graph round trip; materialized YAML loads in `kg/loader.py` |
| Reconcile | duplicate KCs from two docs merge; id assignment is deterministic |
| Extraction | stubbed responses → expected draft; malformed → repair → fallback |
| Approval gate | `approve` on an invalid draft returns 422 and does **not** write YAML |
| Coverage sanity | live-ish fixture run over docs 01 + 06 covers the expected KC ids from `sops/README.md` |

The coverage test asserts *set overlap above a threshold*, not exact equality — PRD §5 calls the mapping "expected/plausible output", not a spec to grade against turn-by-turn.

---

## 9. Explicitly not built (PRD §8.3)

Re-upload diffing/versioning against an approved graph; multi-reviewer approval or RBAC; automatic quality scoring of extracted KCs. The human review step *is* the quality gate.

---

## 10. Risks

- **Extraction cost/latency** — 8 docs × structured output. Mitigation: cache draft results by content hash so demo re-runs are instant, and default the demo to the 2-document subset.
- **Id collision with the seed graph** — reconcile assigns ids per domain; a re-run over a subset will renumber. Mitigation: when the proposed name matches a seed KC name, reuse the seed id. This is also what makes the §8.5 "re-derives the same ids" claim hold.
- **SVG layout on a dense graph** — 24 nodes is fine; guard against pathological layering with a max-per-level wrap.

---

## 11. Done

An employer can upload the corpus, watch extraction, edit a node and an edge, be blocked by a real validation failure, click Approve, and get YAML the runtime agent loads unmodified — with the approval gate enforced server-side.
