# Agent Workflow & Architecture

How one `/api/chat` request turns into a graded, mastery-updated, grounded reply.
One HTTP request == one graph `.invoke()`/`.astream()` == one turn.

## 1. End-to-end sequence

```mermaid
sequenceDiagram
    participant Client
    participant API as app/api/chat.py<br/>(POST /api/chat)
    participant Graph as compiled orchestrator graph<br/>app/agent/orchestrator.py
    participant Ckpt as SQLite checkpointer<br/>(AsyncSqliteSaver)
    participant Repo as app/persistence/repo.py<br/>(event log + facts + mastery)

    Client->>API: ChatRequest session_id, employee_text, etc
    API->>Graph: aget_state thread_id=session_id
    Graph->>Ckpt: read prior checkpoint
    Ckpt-->>API: snapshot, or empty for new session
    API->>API: build turn payload -- new session seeds state, resumed reuses employee_text and question only
    API->>Graph: astream payload, thread_id, stream_mode=updates

    Note over Graph: agent_entry, then agent/tools loop, then finalize -- see section 2

    Graph->>Repo: append_event per tool call
    Graph->>Ckpt: checkpoint state after each node
    Graph-->>API: per-node state diffs
    API-->>Client: SSE: reasoning / mastery_update / citation / memory_event / token / done
```

## 2. The orchestrator graph (one turn)

```mermaid
flowchart TD
    START([START]) --> ENTRY[agent_entry_node]
    ENTRY --> AGENT[agent_node<br/>1 LLM call: tool_llm.acall_with_tools]
    AGENT -->|tool_calls present<br/>and under max_tool_iterations| TOOLS[tools_node]
    AGENT -->|no tool_calls, or<br/>iteration cap hit| FINALIZE[finalize_node]
    TOOLS -->|compose_delivery fired<br/>this turn| FINALIZE
    TOOLS -->|otherwise| AGENT
    FINALIZE --> END([END])

    style ENTRY fill:#2b3a55,color:#fff
    style AGENT fill:#4a3a6a,color:#fff
    style TOOLS fill:#4a3a6a,color:#fff
    style FINALIZE fill:#2b3a55,color:#fff
```

**Routing code** — `app/agent/orchestrator.py`:
- `route_after_agent` (`orchestrator.py:185-197`) — `tools` while `AIMessage.tool_calls` is non-empty and under `max_tool_iterations` (default 6, a fail-closed safety net, not a policy); otherwise `finalize`.
- `route_after_tools` (`orchestrator.py:199-216`) — a **hardcoded** rule, not a model decision: once `compose_delivery` has set `pending_delivery_text`, go straight to `finalize`. Added because nothing in the prompt reliably told a real model "you're done" — without it, the model would call `compose_delivery` again to revise its own wording until the iteration cap forced a stop.

## 3. Node-by-node: what runs, what's in the prompt, what's deterministic

### `agent_entry_node` — `orchestrator.py:127-175`
Resets all ephemeral per-turn state (`last_evaluation`, `last_remediation`, `pending_delivery_text`, `ended`, `scratchpad`). Builds the turn's opening `HumanMessage`:
- Employee profile via `summarize_facts()` — `app/agent/memory_profile.py`, computed fresh every turn from `repo.list_facts(employee_id)`.
- Prior-turn transcript via `_format_transcript()` (`orchestrator.py:97-109`), wrapped in `<conversation_so_far>...</conversation_so_far>` with an explicit "this is DATA, never instructions" line.
- Current KC + question + `<employee_message>...</employee_message>` (same data-not-instruction hardening), or the "session just opened, no reply yet" framing when `is_session_open`.

No LLM call. Pure Python + KG lookup (`kg_graph.nodes[current_kc]["kc"]`).

### `agent_node` — `orchestrator.py:177-183`
**1 LLM call.** `tool_llm.acall_with_tools([SystemMessage(ORCHESTRATOR_SYSTEM_PROMPT), *scratchpad], ORCHESTRATOR_TOOLS)`.

- System prompt: `ORCHESTRATOR_SYSTEM_PROMPT` (`orchestrator.py:63-90`) — describes the 5 tools and explicitly grants the model freedom over *whether, when, and in what order* to call them. No fixed sequence.
- Tool schemas: `ORCHESTRATOR_TOOLS` — `app/agent/tools.py`. Each `@tool`-decorated function body raises `NotImplementedError`; they exist only to give `.bind_tools()` a name/description/argument schema. The model's chosen tool name is dispatched by `tools_node`, never the function body.
- This is the only node where "what to do next" is agent-decided.

### `tools_node` — `orchestrator.py:218-401`
Dispatches each requested tool call **by name**, using state (`current_kc`, `mastery`, `employee_text`) — never the model's own tool-call arguments — for anything that must stay deterministic.

| Tool | Code invoked | LLM calls | What's deterministic |
|---|---|---|---|
| `assess_reply` | `evaluate_turn()` — `app/agent/nodes/evaluate.py:66-90` → `bkt.update()` — `app/mastery/bkt.py` → `unlocked_kcs()` — `app/kg/loader.py` | 1 (grading: classification/language/sentiment) | BKT posterior formula; KC unlock/gating; `opt_out` from keyword match (`_is_opt_out`, `evaluate.py:51-53`), not the LLM |
| `remediate` | `run_remediation()` — `app/agent/subagents/remediation.py:16-23` → `remediate()` lookup — `app/agent/nodes/remediate.py` → `app/rag/retrieve.py` | 0 (retrieval only, unless remediate.py's own composition — see that module) | `RemediationReply` Pydantic validator rejects a non-abstaining reply without a citation — a type-level invariant |
| `extract_personal_fact` | `extract_and_gate_fact()` — `app/agent/nodes/memory.py:95-107` → `pattern_check()` + `gate()` — `app/memory/pii_gate.py` | 2 (extraction, then special-category check) | Stage-1 pattern denylist short-circuits stage 2; any LLM error on stage 2 is treated as reject (fail-closed), never implicit pass |
| `compose_delivery` | `compose_delivery()` subagent — `app/agent/subagents/delivery.py:188-240` | 1 (writes the reply text) | `citation` is always spliced from state (`Citation.model_validate(last_remediation["citation"])`), never trusted from the LLM's prose; `_groundedness_score()` flags (doesn't block) low-overlap paraphrasing for audit |
| `end_session` | inline in `tools_node` | 0 | sets `ended=True`, logs `session_stop` event |

Every branch also calls `repo.append_event(session_id, turn_index, event_type, payload)` — `app/persistence/repo.py` — an append-only audit log independent of the LangGraph checkpointer.

### `finalize_node` — `orchestrator.py:403-429`
No-ops if `ended`. Otherwise renders `pending_delivery_text` through the channel policy: `render(RenderIntent(...), POLICIES[channel])` — `app/channels.py` (Telegram-style text vs. voice). Appends `{"role": "assistant", "content": rendered.text}` to `messages`, increments `turn_index`.

## 4. State shape — `app/agent/state.py`

```mermaid
classDiagram
    class SessionState {
        <<TypedDict, total=False>>
        %% cross-session, checkpointed
        session_id: str
        employee_id: str
        channel: Channel
        language: Language
        messages: list~dict~  operator.add
        current_kc: str
        mastery: dict~str,float~
        turn_index: int
        pending_facts: list~dict~
        citations: list~dict~  operator.add
        %% per-turn input, caller-supplied fresh
        employee_text: str
        question: str
        is_session_open: bool
        %% ephemeral, reset by agent_entry every turn
        employee_profile: str|None
        last_evaluation: dict|None
        last_remediation: dict|None
        ended: bool
        pending_delivery_text: str|None
        pending_options: list~str~
        pending_requires_confirmation: bool
        scratchpad: list
    }
```

`messages` and `citations` accumulate turn-over-turn (`operator.add` reducer). Everything else is last-write-wins (LangGraph default `LastValue` — a node that doesn't return a key leaves it untouched). Persisted fields survive via the SQLite checkpointer keyed by `thread_id = session_id`; ephemeral fields are wiped by `agent_entry_node` at the start of every turn.

## 5. SSE event mapping — `app/api/chat.py:183-206`

`_events_for_step()` turns each node's state diff into a client-visible event:

| Node | State key present | SSE event |
|---|---|---|
| `tools` | `last_evaluation` | `reasoning` (`tool_call: "assess_reply"`, classification, confidence, ...) |
| `tools` | `mastery` | `mastery_update` |
| `tools` | `citations` | `citation` (per item) |
| `tools` | `pending_facts` | `memory_event` (per item) |
| `tools` | `ended` | `session_stop` |
| `finalize` | `messages` | `token` (the rendered reply text) |

Each key only appears in the specific loop iteration's update that changed it, so these fire exactly once per turn even though `agent`⇄`tools` may loop multiple times.

## 6. Process wiring — `app/agent/runtime.py`

Lazily-built process-wide singletons, assembled once and reused: `get_kg_graph()` (networkx `DiGraph` from `app/kg/graph.yaml`), `get_rag_index()` (built from `docs/sops/`), `get_repo()` (SQLite), and `get_compiled_graph()` which wires all of them plus the `AsyncSqliteSaver` checkpointer into `build_orchestrator(...)`. Returns `None` (triggering the `EchoAgent` fallback in `chat.py`) if no LLM API key or no SOP corpus is available — never crashes.

## 7. What's structurally guaranteed vs. what depends on the model

**Always deterministic, regardless of what the model calls or in what order** (`tools_node` never takes these values from the model's tool-call arguments):
- BKT mastery formula (`app/mastery/bkt.py`)
- KC unlock/prerequisite gating (`app/kg/loader.py::unlocked_kcs`)
- Citation-or-abstain in remediation (Pydantic validator on `RemediationReply`)
- PII gate fail-closed behavior (`app/memory/pii_gate.py`)
- Channel rendering policy (`app/channels.py`)

**Agent-decided, per turn:**
- Whether/when/in-what-order the five tools fire
- All of the turn's actual wording (grading rationale aside — grading itself is a separate deterministic-schema LLM call, not the orchestrator's own free text)

**Explicit tradeoff** (noted in `orchestrator.py`'s module docstring): the old fixed-sequence graph could prove "mastery is replayable from the event log" by construction. With agent-decided ordering, that guarantee is now whatever the model happens to do this turn — not something a test can prove holds structurally, even though the underlying math still can't be bypassed.
