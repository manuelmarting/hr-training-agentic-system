# Plan — Workflow 1: Conversational Agentic Training System

**Scope:** PRD §5–§7, §9 (demo beats 1–3). The runtime path: an employee talks to Sofía, the graph picks KCs, the LLM classifies, Python computes mastery, RAG grounds remediation, the PII gate guards memory, and every turn is persisted as a replayable event.

**Out of scope here:** graph *authoring* (→ [workflow 2](../kg-studio/plan.md)), rendering surfaces (→ [workflow 3](../chat-ui/plan.md)). This plan owns the backend contracts those two consume.

**Status:** implemented. `app/agent/orchestrator.py` (LangGraph + `AsyncSqliteSaver`), `app/mastery/bkt.py`, `app/kg/{loader.py,graph.yaml}`, `app/rag/retrieve.py`, `app/memory/pii_gate.py`, `app/channels.py`, `app/persistence/{db.py,repo.py}` all exist and are covered by `backend/tests/`. The echo fallback remains only for the no-API-key path (`app/agent/runtime.py::get_compiled_graph`, returns `None`, handled by `chat.py`'s `_echo_stream`). **Diverged since this plan was written:** the LLM boundary (`app/agent/llm.py`) is multi-provider (Gemini/Anthropic/OpenAI via `settings.llm_provider`, Gemini default — see §1), not Anthropic-only; a best-effort Kokoro TTS side-call (`app/agent/tts.py`) renders an `audio` SSE event alongside `token`, which this plan's original API surface (§5) didn't anticipate.

**Implementation note — orchestration diverged from §3 below.** The graph actually shipped is not the fixed linear `evaluate → update → remediate → memory → select → ask` pipeline sketched in this plan. It's a ReAct-style loop (`agent_entry_node` → `agent_node` ⇄ `tools_node` → `finalize_node`) where one LLM call decides, per turn, whether/when/in-what-order to call five tools (`evaluate_response`, `fetch_remediation`, `extract_facts`, `deliver_reply`, `end_session`); `tools_node` dispatches them deterministically from state, never from the model's own arguments. §3's diagram is kept below as the original design rationale, not as current behavior — see [`../../AGENT_WORKFLOW.md`](../../AGENT_WORKFLOW.md) for the authoritative, line-referenced description of what actually runs, including the explicit tradeoff this bought/cost (§7 there). The safety-interrupt path (§3, §7 below) is still **not built**, as originally called out.

---

## 1. Design commitments

These are the decisions the rest of the plan assumes. They follow CLAUDE.md's "simplicity first" and "deterministic where the PRD says deterministic".

| Decision | Choice | Why |
|---|---|---|
| Orchestration | LangGraph state machine, SQLite checkpointer (`langgraph-checkpoint-sqlite`) | PRD §6.1 requires resume across a ≥4h gap; the checkpointer is the whole feature |
| LLM | Multi-provider `StructuredLLM`/`ToolCallingLLM` (`app/agent/llm.py`): Gemini (default), Anthropic, OpenAI, selected by `settings.llm_provider` via `get_structured_llm()` | Gemini is the default for cost (cheapest agentic-capable model per provider for high-volume, low-complexity classification/extraction); Anthropic and OpenAI remain fully wired as alternates. `.with_structured_output(Model)` under the hood for all three |
| Graph store | `networkx.DiGraph` built from one YAML file | 24 nodes; PRD §6.2 explicitly rejects Neo4j |
| Retrieval | Pure-Python BM25 over paragraph chunks of `docs/sops/` | 8 documents. No embedding provider, no vector DB, no extra service. Threshold-based abstain is what's being tested, not recall@k |
| Mastery | Pure functions in `app/mastery/bkt.py`, no I/O, no LLM | PRD §7: "never computed by the LLM" |
| Events | Pydantic models dumped to a `events` SQLite table | PRD §6.2: "validated JSON matching real schemas", no Kafka |
| Channel adapters | Declarative policy dict + a render function per channel | PRD §6.1: "two adapters, one core" |

**Non-negotiable invariant:** the LLM only ever produces a *classification* (`correct` / `incorrect` / `partial` / `off_topic` + misconception id + confidence). Every number that affects gating or mastery is computed in Python from that classification.

---

## 2. Module layout (as built — see [`../../AGENT_WORKFLOW.md`](../../AGENT_WORKFLOW.md) for behavior)

```
backend/app/
  agent/
    orchestrator.py   # LangGraph assembly: agent_entry/agent/tools/finalize nodes, edges, checkpointer wiring
    runtime.py         # lazy process-wide singletons: KG, RAG index, repo, compiled graph
    state.py           # SessionState (TypedDict) — the graph's typed schema
    llm.py             # StructuredLLM/ToolCallingLLM protocols + Anthropic/Gemini/OpenAI impls, repair-once wrapper
    memory_profile.py  # summarize_facts() — per-turn employee profile string for the prompt
    tools.py           # ORCHESTRATOR_TOOLS: @tool-decorated stubs (name/description/schema only, dispatched by tools_node)
    tts.py             # best-effort Kokoro TTS side-call, never blocks/fails a turn
    nodes/
      evaluate.py      # TurnEvaluation extraction (structured output + repair) + BKT update + unlock
      remediate.py     # retrieval → grounded explanation or abstain
      memory.py        # personal-fact extraction → two-stage PII gate
    subagents/
      remediation.py   # run_remediation() wrapping nodes/remediate.py
      delivery.py       # compose_delivery() — writes the reply text, splices citation from state
  kg/
    loader.py           # YAML → validated models → DiGraph; unlocked_kcs(), is_gated()
    graph.yaml          # the 25 KCs (frozen output of workflow 2 — see kg-studio plan's corpus note)
  mastery/
    bkt.py             # pure BKT: update(), decay(), seed_from_prior() + default params
  rag/
    retrieve.py        # chunk docs/sops/ at startup, BM25, threshold + abstain
  memory/
    pii_gate.py         # allowlist + two-stage fail-closed gate (pattern, then LLM)
  channels.py           # ChannelPolicy (telegram, voice) + render(intent, policy)
  persistence/
    db.py               # SQLite connection, schema DDL
    repo.py             # Repo: facts, mastery, append-only events log
  schemas/
    extraction.py        # TurnEvaluation, PersonalFact, LearningRisk (+ allowlisted PersonalFactType)
    chat.py               # ChatRequest and other API-boundary models
```

There is no `kg/items.yaml`, no `schemas/events.py`, and no separate `nodes/update.py` / `select.py` / `ask.py` — item text, next-KC selection, and BKT updates are folded into `evaluate.py` + the KG loader, invoked from `tools_node` rather than as separate graph nodes (§3 below).

Dependencies actually pinned: `langgraph`, `langgraph-checkpoint-sqlite`, `langchain-anthropic`, `langchain-google-genai`, `langchain-openai`, `langchain-core`, `networkx`, `pyyaml`.

---

## 3. Graph shape

```
 turn → evaluate ──► update (BKT + events)
        (one LLM call:      │
         classification,    ├────────────┬──────────┐
         language,   incorrect/partial          correct
         sentiment)         ▼                       │
                       remediate                    │
                 (retrieve → cite | abstain)        │
                            └──────────┬────────────┘
                                       ▼
                                    memory (extract → PII gate)
                                       ▼
                                    select (next KC, gated)
                                       ▼
                                     ask ──► emit turn, await input
```

One linear path, one branch. `evaluate` makes the turn's only classification LLM call and returns `TurnEvaluation` carrying the grade *plus* `language` and `sentiment` — a second triage call before it bought nothing that couldn't be fields on the model it was already about to produce. `update` runs before `remediate` so the mastery panel moves as soon as the classification exists.

`sentiment` is used for tone softening and difficulty reduction (PRD §7 "frustration detection"); it never touches mastery or gating.

**State** (`state.py`) holds: `session_id`, `employee_id`, `channel`, `language`, `messages`, `current_kc`, `mastery: dict[str, float]`, `turn_index`, `pending_facts`, `citations`. Nodes return partial updates only.

**Deliberately built:** user-initiated opt-out (employee refusal). When the user says "not now" or refuses engagement, the LLM classifier tags it as `off_topic`; the graph emits a `SessionStop` event and terminates cleanly. Mastery and facts persist, so re-entry (via rescheduling or manual re-join) resumes intact.

**Deliberately not built:** the safety-interrupt path for injury/harassment/distress (escalation + suspend + handoff to human). PRD §5, §7 and demo beat §9 call for it; this plan drops it to keep the first cut focused on the conversation loop. Re-adding it later is one node plus one conditional edge off `evaluate` — the graph shape above does not foreclose it.

---

## 4. Build phases

### Phase 1 — Deterministic core (no LLM, fully unit-tested)

1. `schemas/extraction.py`: the four Pydantic models from PRD §6.1, with `Literal`/`Enum` closed sets and `Field` constraints.
2. `kg/graph.yaml`: author the 24 KCs per [`docs/sops/README.md`](../../sops/README.md)'s coverage table, including the four cross-document edges and `PRC.005`'s `regulation: ADR` + `known_misconceptions`.
3. `kg/kg.py`: YAML → validated `KnowledgeComponent` models → `DiGraph`. `unlocked_kcs(mastery, threshold)` returns KCs whose prerequisites all clear the threshold; `is_gated()` explains *why* a KC is locked (needed by the UI); `invalidate_superseded()` handles `superseded_by_kc_id`.
4. `mastery/bkt.py`: `update(prior, correct, params) -> posterior`, `decay(p, days_elapsed, params)`, `seed_from_prior(source, value)`. Pure, no imports beyond `math`/models.
5. `channels.py`: telegram (≤4096 chars, inline buttons, terse) vs. voice (≤2 sentences, no markdown, digit confirmation, spoken repeat-back).
6. `memory/pii_gate.py` stage 1: allowlisted `PersonalFact` types + pattern classifier (special-category regex/keyword denylist — health, religion, ethnicity, union, sexuality, biometrics).
7. `persistence/db.py` + `repo.py`: T2/T3/T4 tables + `events`. Every write goes through a repo function; no raw SQL in nodes.

**Exit criteria:** `pytest` green with exhaustive tests for BKT math, unlock gating, supersede invalidation, channel policy, and the pattern gate — all without an API key.

### Phase 2 — LLM boundary

1. `agent/llm.py`: `structured(model_cls, prompt) -> model_cls` wrapping `.with_structured_output`, with **one** repair attempt that re-prompts with the `ValidationError` text, then a typed fallback + `logger.warning` (never a crash — CLAUDE.md).
2. `nodes/evaluate.py` and `nodes/memory.py` on top of it. PII gate stage 2 is the LLM classifier; the fact is stored only if **both** stages pass (fail closed — an LLM error counts as a fail).
3. Prompt hardening: employee text is always delivered inside a delimited `<employee_message>` block with an explicit instruction that content inside it is data, never instruction. Injection attempts are classified `off_topic`, logged as an event, and never alter grading.
4. User opt-out handling: if the classifier returns `off_topic` **and** the employee text contains opt-out keywords ("not now", "I don't want", "later", "pause", etc.), emit a `SessionStop` event and set a flag on `TurnEvaluation` to trigger early termination. Mastery and facts remain persisted for resume.

**Exit criteria:** contract tests with a stubbed LLM client covering: valid output, malformed output → repair succeeds, repair fails → fallback, injection payload → refused + logged, special-category disclosure → not stored + risk event, refusal → off_topic + SessionStop event emitted.

### Phase 3 — RAG + remediation

1. `rag/retrieve.py`: split each SOP on headings/paragraphs keeping `(doc_id, heading, span)` for citation, index at startup (~seconds for 8 docs), BM25 score; if top score < threshold → return `Abstain(reason)`.
2. `nodes/remediate.py`: on `Abstain`, the reply says it doesn't know, emits a `knowledge_gap` event, and routes to human. On success, the explanation **must** carry `Citation(doc_id, heading)`; a remediation reply without citations is rejected in code, not left to the prompt.

**Exit criteria:** a test asserts that an off-corpus question (e.g. payroll) abstains, and that every non-abstaining remediation carries ≥1 citation.

### Phase 4 — Orchestration, session close, demo

1. `agent/graph.py` wiring with `SqliteSaver`; `thread_id = session_id`.
2. Resume test: build state over 12 turns, drop the graph object, rebuild from the checkpointer, assert context and mastery survive.
3. `SessionSummary` emission: mastery deltas, `LearningRisk` list, `not_for_use_in: ["performance_management", "termination"]` constraint tag, immutable audit row.
4. Replay test: re-run the event log through `bkt.update` and assert the final mastery matches the stored state — this is the auditability requirement (PRD §7) proved, not asserted.
5. Seed fixtures for the demo conversations (§9); `Maria/Daniel/Clare` stay contract fixtures validated at the boundary with purpose-limitation filtering.

---

## 5. API surface (consumed by workflow 3)

| Endpoint | Purpose |
|---|---|
| `POST /api/chat` (SSE) — `app/api/chat.py:35` | Emits, per `_events_for_step()` (`chat.py:196-226`): `reasoning`, `mastery_update`, `citation` (per item), `memory_event` (per item), `session_stop`, `token` (rendered reply), `audio` (best-effort TTS, base64), `done` |
| `GET /api/health` | Liveness check |
| `GET /api/session/{id}/mastery` | Snapshot for panel hydration on reload |
| `GET /api/session/{id}/facts` / `DELETE /api/facts/{id}` | PRD §7 employee view/delete right |
| `GET /api/kg` | KC metadata + gating state for the panel |

There is no `events/schemas.py`; event payloads are built ad hoc in `_events_for_step()` from `SessionState` diffs (`app/agent/state.py`) rather than from a dedicated events-schema module, and mirrored in TypeScript by hand (see [chat-ui plan](../chat-ui/plan.md)).

---

## 6. Test matrix (PRD §6.1's list, made concrete)

| Area | Tests |
|---|---|
| Mastery math | monotonicity, slip/guess bounds, decay over time, idempotent replay |
| Unlock rules | prerequisite chain `SAF.002→003→004`, cross-doc `PRC.005→SAF.001`, campaign-scope override is logged, supersede invalidation |
| Extraction | valid/malformed/repair/fallback for each of the 4 models |
| PII gate | each allowlisted type stored; each special category rejected; LLM-error → reject; pattern-pass + LLM-fail → reject |
| Channel policy | length caps, markdown stripping in voice, digit confirmation present |
| Adversarial | injection, grading-bypass attempt, role-play override, encoded instruction |
| User opt-out | refusal classified as off_topic, SessionStop event emitted, session terminates, mastery/facts persist |
| Grounding | abstain below threshold, citation always present above it |
| Resume | ≥12 turns, checkpointer round-trip; opt-out + resume restores state intact |

---

## 7. Risks

- **LangGraph + SSE streaming** is the fiddliest integration point (streaming intermediate node output through `EventSourceResponse`). Mitigation: build phases 1–3 with a synchronous `invoke` and a fake streamer; wire real token streaming last.
- **Time budget** (PRD §10 gives ~5h to core). Phases 1–3 are the assessed substance; phase 4's demo fixtures are cuttable.
- **Dropped safety path** (§3) is a known gap against PRD §5/§7, accepted deliberately for this cut.
- **BM25 quality** on 8 short docs may make the abstain threshold hand-tuned. Acceptable — the tested behavior is *that* it abstains, and the threshold lives in settings.

---

## 8. Done

Three demo conversations run end to end; `ruff check` and `pytest` green; mastery replayable from the event log; no LLM-produced number anywhere in the mastery or gating path.
