"""The orchestrator's typed state schema. Nodes take state and return partial
updates; `messages`/`citations` accumulate turn-over-turn via the `operator.add`
reducer, everything else is last-write-wins (LangGraph's default `LastValue` channel:
a node that doesn't return a given key leaves its previous value untouched).

One `.invoke()` == one turn, but a turn is no longer one hardcoded node sequence — the
orchestrator's `agent`/`tools` nodes loop an agent-decided number of times before
`finalize` renders whatever `compose_delivery` produced. `employee_text`/`question`/
`is_session_open` are the per-turn input the caller supplies fresh each time; every
other field either comes from the initial session setup or is restored by the
checkpointer on a resumed thread. `employee_profile` is recomputed every turn by
`agent_entry` from stored facts (`app/agent/memory_profile.py`), so it's grouped with
the other ephemeral fields even though its *source* (the fact store) persists
cross-session.
"""

import operator
from typing import Annotated, Literal, TypedDict

Channel = Literal["telegram", "voice"]
Language = Literal["es", "en", "ro"]


class SessionState(TypedDict, total=False):
    session_id: str
    employee_id: str
    channel: Channel
    language: Language
    messages: Annotated[list[dict], operator.add]
    current_kc: str
    mastery: dict[str, float]
    turn_index: int
    pending_facts: list[dict]
    citations: Annotated[list[dict], operator.add]

    # Per-turn input.
    employee_text: str
    question: str
    # Caller-supplied fresh every turn by `app/api/chat.py`, so it self-resets via
    # `LastValue` semantics rather than needing `agent_entry` to clear it. True only
    # for the turn that opens a brand-new session, before the employee has said
    # anything — `agent_entry_node` branches on it to skip the `<employee_message>`
    # framing and `tools_node` refuses `assess_reply`/`remediate` while it's set.
    is_session_open: bool

    # Ephemeral inter-node handoff — meaningful only within the turn that set it;
    # `agent_entry` resets all of these at the start of every turn.
    employee_profile: str | None
    last_evaluation: dict | None
    last_remediation: dict | None
    ended: bool
    pending_delivery_text: str | None
    pending_options: list[str]
    pending_requires_confirmation: bool

    # The current turn's tool-calling transcript (LangChain messages). Reset by
    # `agent_entry`; never read by anything outside the orchestrator graph.
    scratchpad: list
