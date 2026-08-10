# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

**Sofía** — a continuous training & assessment agent for frontline employees (MVP slice). Read **`docs/PRD.md`** before implementing anything; `docs/VISION.md` holds the full product rationale. The slice's hard parts are: KG-driven KC selection with prerequisite gating, BKT mastery updates, grounded remediation with mandatory citations, a fail-closed PII gate, and the employer-facing KG-authoring studio (PRD §8).

Do NOT use OpenSpec in this repo — implement directly.

## Repository layout

- `backend/` — FastAPI app (`app/`), tests (`tests/`). Python ≥3.11, deps pinned in `requirements.txt` / `requirements-dev.txt`; `pyproject.toml` holds ruff + pytest config only.
  - `app/agent/` — agent core (`base.py` defines the `Agent` interface; the LangGraph ReAct orchestrator lives in `orchestrator.py`, subagents in `subagents/`).
  - `app/api/` — FastAPI routes (streaming chat via `sse-starlette`).
  - `app/schemas/` — Pydantic models.
  - `app/static/` — frontend build output, served by FastAPI at `/`.
- `frontend/` — React 18 + TypeScript + Vite chat UI (plus the studio route, PRD §8). Builds into `backend/app/static/`.
- `docs/sops/` — the 8-document SOP corpus: both the RAG grounding source and the input the studio pipeline derives the 24-KC graph from.
- `docker/`, `docker-compose.yml` — local dev; `.github/workflows/ci.yml` — ruff + pytest + frontend lint/build.

## Commands

```bash
# Backend (from backend/)
pip install -r requirements-dev.txt
ruff check . && ruff format .
pytest
uvicorn app.main:app --reload        # :8000

# Frontend (from frontend/)
npm run dev                          # :5173, proxies /api → :8000
npm run lint
npm run build                        # tsc -b + vite build → backend/app/static
```

Run `ruff check` and `pytest` after every backend change; `npm run lint` and `npm run build` (which type-checks) after every frontend change.

## Core principles

### Simplicity first

- Prefer the simplest implementation that satisfies the PRD. This is a scoped 4–6h assignment slice, not production infrastructure.
- Pure functions over classes where possible (the BKT mastery engine should be pure functions with unit tests).
- 24 KCs live in YAML loaded into `networkx` — no Neo4j. SQLite — no Postgres server required. Single process — no Kafka; events are validated JSON emitted in-process.
- Don't add abstraction layers, config options, or generality the PRD doesn't ask for. Mocked boundaries (telephony, Maria/Daniel/Clare) stay mocked — see PRD §6.2.

### Pydantic everywhere data crosses a boundary

- All structured LLM extraction goes through Pydantic models: `TurnEvaluation`, `PersonalFact`, `SessionSummary`, `LearningRisk` (PRD §6.1).
- Validation failure on LLM output triggers a **repair pass** (re-prompt with the validation error), never a crash. One repair attempt, then a safe fallback + log.
- API request/response bodies, emitted events, and settings (`pydantic-settings`) are all Pydantic models. No raw dicts across module boundaries.
- Use Pydantic v2 idioms: `model_validate`, `model_dump`, `Field` constraints, `Literal`/`Enum` for closed sets, discriminated unions where variants exist.

## LangChain / LangGraph

The conversation core is a **LangGraph ReAct orchestrator** with a checkpointer (SQLite) so sessions are resumable across hours (PRD §6.1). References:

- LangGraph docs: <https://langchain-ai.github.io/langgraph/> (concepts: <https://langchain-ai.github.io/langgraph/concepts/>)
- Persistence/checkpointers (SQLite): <https://langchain-ai.github.io/langgraph/concepts/persistence/>
- Human-in-the-loop / interrupts (for the escalation path): <https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/>
- Structured output with Pydantic: <https://python.langchain.com/docs/concepts/structured_outputs/>
- Tool calling: <https://python.langchain.com/docs/concepts/tool_calling/>
- LangChain docs: <https://python.langchain.com/docs/introduction/>

Conventions:

- Graph state is a typed schema (TypedDict or Pydantic model); nodes are small functions that take state and return partial updates.
- Use LangGraph `interrupt` for the safety-escalation path (injury/harassment/distress → suspend + handoff).
- Use `.with_structured_output(PydanticModel)` for extraction (grading, memory, delivery composition); wrap it with the repair-pass logic above. Use `.bind_tools(...)` only for the orchestrator's own tool-selection loop.
- Tools the orchestrator can call are thin dispatch targets, not the logic itself: `app/agent/tools.py` only defines names/descriptions/schemas for `.bind_tools()`; `orchestrator.py`'s `tools_node` is what actually invokes the mastery engine, KG traversal, and PII gate — all still plain Python modules, still unit-testable without an LLM.

## Python best practices

- Type hints on all function signatures; modern syntax (`X | None`, `list[str]` — ruff `UP` enforces this).
- Ruff is the formatter and linter (line length 100, rules `E,F,I,UP,B`). No `# noqa` without a reason.
- Small modules with single responsibility; `pathlib` over `os.path`; f-strings; dataclasses/Pydantic over dict-passing.
- Async in FastAPI routes; don't block the event loop (LLM calls and DB access use async clients or `run_in_executor`).
- Tests: pytest, mirroring PRD §6.1's list — extraction accuracy, mastery math, unlock rules, PII gate (including special-category attempts), adversarial/injection inputs, grounding-abstain.
- No secrets in code — `.env` via `pydantic-settings` (see `backend/.env.example`).

## Frontend best practices

- TypeScript strict; `npm run build` runs `tsc -b` — keep it green. No `any` unless unavoidable and commented.
- Function components + hooks; small components with single purpose; ESLint (`react-hooks`, `react-refresh` plugins) must pass.
- The mastery panel (PRD §7) is a **live view onto backend state**, updated per turn from the SSE stream — never compute or fake mastery numbers client-side.
- Handle SSE/fetch errors visibly (retry or a clear error state), and render loading states — an assessment session must not silently hang.
- Studio UI (PRD §8) is a second route in the same app, not a separate app. Approval gate is explicit: nothing reaches the runtime graph without the Approve action.
- Keep dependencies minimal — prefer what's already in `package.json`; justify any new dependency.

## Non-goals — do not build

Auth, multi-tenancy, admin UI, real telephony integrations, Neo4j, Kafka, Clare dashboard, certifications, or anything feeding performance management (PRD §3). If a task seems to need one of these, stop and re-read the PRD's mock strategy (§6.2).
