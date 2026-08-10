# PRD — Sofía: Continuous Training & Assessment Agent (MVP slice)

**Product area:** Orbio AI agent suite (4th agent)
**Author:** Manuel Martín Gómez
**Status:** Draft — scoped for the Core Engineer assignment (4–6h build)
**Version:** 0.1 — August 2026

> Condensed from `docs/VISION.md`, which is the full product vision (§1–13) plus the assignment slice (§14). This document extracts only what's needed to scope and build the slice. See VISION.md for the complete rationale, architecture, regulatory analysis and roadmap.

---

## 1. TL;DR

Sofía is a multi-language agent that runs short conversational assessments and micro-training sessions with frontline employees, maintains a per-employee mastery model over a role-specific skills knowledge graph, and emits structured competency, risk and action data. The wedge: **completion is not competence**, and today nobody can answer "which of my people can actually do the thing, right now?"

This PRD scopes the **narrow vertical slice** built for the assignment: the hard parts of the real system (KG-driven selection, deterministic mastery updates, grounded remediation, the PII gate) implemented and tested, with everything else explicitly mocked.

---

## 2. Problem statement

Frontline employers are legally obliged to train workers and keep them competent as SOPs change. In practice: training happens once at induction and decays; completion is tracked but not competence; coverage is worst where turnover is highest; workers are hard to reach (no email, shared devices, gloves on, multilingual); and gap signal never reaches the people who could act on it.

---

## 3. Goals and non-goals

### Goals
- Demonstrate a conversational core with best-effort spoken output (TTS) alongside the text turn.
- Show knowledge-graph-driven KC selection with prerequisite gating.
- Show deterministic, auditable mastery updates (BKT), never computed by the LLM.
- Show grounded remediation: procedural claims must cite a source SOP or the agent abstains.
- Show a fail-closed PII/personal-fact memory gate that never stores special-category data.
- Show safety-interrupt handling (injury, distress, harassment → human handoff).

### Non-goals (for this slice, per VISION.md §4.2)
- Authoring long-form content or replacing an LMS.
- Issuing legally valid certifications.
- Performance management, ranking, or termination input — never in scope for Sofía at all.
- Real production integrations (telephony credentials, Neo4j, Kafka, live Maria/Daniel/Clare).
- Auth, multi-tenancy, admin UI, Clare dashboard.

---

## 4. Users and core stories

| Persona | JTBD |
|---|---|
| **Ana**, warehouse operative | Get asked short questions in her language, hands-free or on her phone, without feeling stupid |
| **Marc**, shift supervisor | Know who is/isn't ready for a task before rostering them |
| **Lucía**, HR/L&D lead | Prove training coverage to an auditor without chasing people |

Priority stories for the slice (see VISION.md §5.1 for full list):
1. Employee completes a short assessment in chat, in their own language.
2. Employee gets immediate, explained feedback on wrong answers.
3. Employee gets a spoken read-back of each reply, best-effort.
4. Employee can say "not now" and be rescheduled.
5. Employee can see and delete what Sofía remembers about them.
6. Session escalates immediately to a human on injury/harassment/distress.
7. Employee input can't be used to inject instructions or bypass grading.

---

## 5. Domain model (scoped subset)

Knowledge graph for role `warehouse_operative`: **24 Knowledge Components (KCs)** across 5 domains (Safety & regulatory, Equipment, Process, Systems/WMS, Behavioural), connected by a **single predicate**:

| Predicate | Meaning | Exercised by |
| --- | --- | --- |
| `prerequisite_of` | Mastery of A required before B is teachable | Unlock/lock gating (§7) |

Everything else that VISION.md §6 models as a KC-to-KC edge is a plain **attribute on the KC record** instead, because it doesn't need graph traversal — it's a lookup, not a path:

| Attribute | Meaning | Used for |
| --- | --- | --- |
| `regulation` | Regulation/SOP the KC is required by (e.g. `ADR`) | Compliance tagging, hard expiry |
| `known_misconceptions` | KC id(s) commonly confused with this one | Distractor generation, grounded remediation, the `misconception match` field (§7) |
| `superseded_by_kc_id` | Id of the KC that replaces this one on SOP version bump | Invalidate stale mastery, re-queue (§7) |

VISION.md §6 defines a richer 9-predicate model for the full product (also adding `component_of`, `specialises`, `co_requisite_of`, `assessed_by`, `transfers_to` as true edges), used for composite competence roll-ups, cross-site prior transfer, and session-packing optimisations. None of those are required to demonstrate KG-driven selection, deterministic mastery, or grounded remediation, so the slice's graph stays as simple as it can be: 24 KCs, 1 predicate, one role.

Example: `KC.PRC.005` (dangerous-goods recognition) requires `SAF.001` as prerequisite, has `regulation: ADR`, and lists the limited-quantity/excepted-quantity distinction under `known_misconceptions` — a misconception an LMS completion rate can't surface.

**Provenance:** this 24-KC graph is not hand-typed YAML invented for the demo — it is the frozen, employer-approved *output* of the §8 studio workflow, run once ahead of time over the 8-document SOP corpus in [`docs/sops/`](sops/) (indexed in [`docs/sops/README.md`](sops/README.md), which also maps each SOP to the KCs and cross-document `prerequisite_of` edges it's expected to produce). That corpus doubles as the RAG grounding source in §6.1 — the same documents an employer would upload in §8 are what the agent cites during remediation in §7, so a KC's prerequisite edge, its `regulation`/`known_misconceptions` attributes, and the citation the agent gives when remediating it all trace back to the same source paragraph.

---

## 6. Scope of the build

### 6.1 In scope (real, tested code)

| Capability | Implementation |
|---|---|
| Conversation core | Python + LangGraph state machine; SQLite checkpointer (`AsyncSqliteSaver`); resumable across hours |
| Voice output | Best-effort TTS (Kokoro) read-back of each turn's reply alongside the text; an unreachable TTS service degrades to text-only, never fails the turn |
| Chat UI mastery panel | Web chat surface renders a live panel on the right-hand side of the conversation listing the KCs being exercised in the current session, each with a mastery-probability indicator that updates turn-by-turn as BKT posteriors update |
| Chat UI layout & agent transparency | Full-height, three-column chat surface (VISION.md-aligned demo chrome, not a separate app): a left-hand rail streaming the personal-fact/memory items as they're extracted turn-by-turn, a center conversation column labeled **Sofía** as the agent identity, and the right-hand mastery panel above. Each Sofía turn is preceded by a collapsed, greyed-out "reasoning" container (expandable) showing the agent's reasoning trace and any tool calls made for that turn, before the rendered reply. Employee messages render any attached profile photo inline in a WhatsApp-style rounded chat bubble |
| Knowledge graph | 24 KCs in YAML, loaded into `networkx`; prerequisite/unlock traversal. Materialized by the §8 studio pipeline from the SOP corpus below, not hand-typed |
| Mastery engine | Bayesian Knowledge Tracing with per-KC slip/guess/learn + decay; pure functions, unit-tested |
| Structured extraction | Pydantic models (`TurnEvaluation`, `PersonalFact`, `SessionSummary`, `LearningRisk`) with validation-failure repair path |
| Personal-fact memory | Allowlist + two-stage fail-closed PII gate; tested against special-category attempts |
| RAG | The same 8-document SOP corpus (`docs/sops/`) the §8 pipeline reads to build the graph, chunked + embedded; citation required or the agent abstains |
| Multi-language | ES/EN/RO, per-turn detection, mid-conversation code-switching |
| Frustration detection | Sentiment classifier → tone softening, difficulty reduction, escalation flag |
| Persistence | SQLite with real T2 (learner model) / T3 (personal facts) / T4 (episodic archive) schemas; replayable events |
| Escalation | Interrupt path for injury/harassment/distress → suspend, hand off, minimal retention |
| User opt-out / session pause | Employee can refuse training ("not now"); classified as off-topic, emits SessionStop event, session pauses — resumes only if rescheduled by the system or employee re-joins manually |
| Tests | pytest: extraction accuracy, mastery math, unlock rules, PII gate, adversarial/injection inputs, grounding-abstain behavior |

### 6.2 Mocked / out of scope (stated explicitly)

| Mocked | Why | What proves it works anyway |
|---|---|---|
| Real telephony creds (for voice input) | No business account, provisioning time | Text-only session; TTS output is real, speech input is not attempted |
| Neo4j | 24 KCs fit in `networkx` | Same traversal API, swappable backend |
| Kafka / event bus | Single process | Events emitted as validated JSON matching real schemas |
| Maria / Daniel / Clare | Not available | Contract fixtures + schema validation at the boundary, including purpose-limitation filtering |
| Auth, multi-tenancy, admin UI | Not what's being assessed | — |
| Clare dashboard | — | Emitted `learning_risk` / `mastery_snapshot` payloads |

---

## 7. Requirements (must-have for the slice)

Adapted from VISION.md §10.1 to the slice's scope:

- **Multi-turn assessment**: every turn produces a validated structured record (KC, classification, misconception match, confidence) persisted before the next turn. Schema failures trigger a repair pass, never a crash. Context holds across ≥12 turns and a ≥4h resume gap.
- **Live KC mastery panel in chat UI**: the web chat surface shows a panel to the right of the conversation listing the knowledge component(s) the employee is currently being assessed on, each with its current mastery probability. As the conversation progresses and BKT posteriors update from the employee's answers, each KC's displayed probability updates in step (increasing on correct/confirming evidence, per the BKT update in §7's mastery-engine requirement) — the panel is a live view onto the mastery engine's state, not a separate mock. This is a lightweight in-session view scoped to the demo chat UI; it is distinct from, and does not replace, the out-of-scope Clare dashboard (§3, §6.2).
- **Chat UI layout, agent identity, and reasoning transparency**: the chat surface occupies the full vertical height of the window, with the right-hand margin reserved for the mastery panel above so the two never compete for space. The agent's turns are labeled **Sofía** throughout the UI — no generic "assistant" or "bot" labeling. Each Sofía turn renders a collapsed, greyed-out, expandable container immediately above the reply, holding that turn's reasoning trace and the list of tool calls (name + key args) it made before answering; collapsed by default so it doesn't compete with the conversation for attention, but always present so the interaction stays auditable to the employee/reviewer. When the employee's turn includes a profile photo, it renders inline inside their chat bubble, WhatsApp-style (rounded bubble, image inset at the top, any accompanying text below). To the left of the conversation, a **memory extraction log** streams each `PersonalFact` (or attempted-and-rejected fact, per the PII gate in §7) as a timestamped line the moment it's extracted, so fact capture is visible in real time rather than only inspectable after the session ends.
- **KC selection with unlock gating**: no KC assessed while a prerequisite is unmastered, unless explicitly in campaign scope (and logged). A KC's `superseded_by_kc_id` invalidates and re-queues affected mastery on SOP version change.
- **Deterministic mastery updates**: every change traceable to an observation with session/turn provenance; replayable from the event log.
- **Non-PII personal-fact memory**: allowlisted types only; special-category content never written; both classifiers (pattern + LLM) must pass; employee can view/delete facts.
- **Retrieval-grounded procedural content**: citations required; below-threshold retrieval → abstain, log the gap, route to human.
- **Escalation**: injury/harassment/distress → immediate handoff, conversation suspended, minimal retention.
- **User opt-out / session pause**: employee refusal ("not now", "I don't want to", etc.) is classified as `off_topic`, emits a `SessionStop` event, and cleanly terminates the session; mastery and facts persist so the session resumes intact if rescheduled.
- **Multi-language**: per-turn detection, mid-conversation switching; regulatory KC items localized, not machine-translated at runtime.
- **Session summary + events**: every session emits summary, mastery deltas, risks/actions, and a `not_for_use_in` constraint tag; immutable audit log entry per session.

---

## 8. Parallel workflow: employer-authored KG construction (studio UI)

Everything above assumes the 24-KC `warehouse_operative` graph already exists. This section scopes a **second, independent workflow** for the demo: how that graph gets built in the first place, from an employer's own SOPs, with a human in the loop before anything is trusted for assessment.

This is deliberately **not** part of the conversational agent's runtime path — it's an authoring/admin surface that produces the artifact §5–§7 consume. It exists to show the other hard part of the pitch: Sofía isn't hand-fed a curated graph, an employer can point it at their own documents and get one out, but the graph is never trusted un-reviewed.

### 8.1 Goal

Employer (Lucía, HR/L&D lead, or a role-family owner) uploads several SOP documents for a role, an LLM proposes a KC taxonomy and a `prerequisite_of` graph from them, and the employer reviews and edits the proposal node-by-node before anything is materialized for the runtime agent to use.

### 8.2 In scope for the demo

| Capability | Implementation |
|---|---|
| Ingestion UI | Drag-and-drop SOP upload (PDF/text), same frontend shell as the chat demo — a second tab/route, not a separate app |
| Taxonomy extraction | LLM pass over the uploaded SOPs proposes KC candidates (id, name, domain, description, source SOP span) and candidate `prerequisite_of` edges, using the same 5-domain / single-predicate shape as §5 |
| Graph review UI | Node-link view of the proposed graph; click a node to edit its attributes (name, domain, `regulation`, `known_misconceptions`, `superseded_by_kc_id`); add/remove/redirect `prerequisite_of` edges; add or delete nodes entirely |
| Provenance | Each proposed node keeps a pointer back to the source SOP excerpt it was extracted from, shown alongside the edit panel, so the employer is reviewing a claim against its source, not a bare assertion |
| Approval gate | Nothing is usable by the agent until the employer clicks **Approve**. Pre-approval state is a draft, editable and re-runnable; post-approval state is the frozen input to materialization |
| Materialization | On approve, the reviewed graph is serialized to the same YAML shape §6.1 loads into `networkx`. The demo's own 24-KC seed graph (§5) *is* an approved output of this step, produced ahead of time from the corpus in `docs/sops/` — the pipeline isn't a separate toy path, it's how the graph the runtime agent already uses came to exist |

### 8.3 Explicitly mocked / out of scope for the demo

| Mocked | Why |
| --- | --- |
| Versioning/diffing an already-approved graph against a re-upload | Single approve pass is enough to show the mechanic; SOP-update re-extraction is a roadmap item, not a slice requirement |
| Multi-reviewer approval / role-based access on the studio UI | No auth in this slice (§3 non-goals) |
| Automatic quality scoring of extracted KCs | The human review step is the quality gate for this slice, not a model-confidence heuristic |

### 8.4 Why this is a separate demo workflow, not folded into §9's assessment demo

It exercises a genuinely different failure mode than the conversational agent: instead of "does the agent stay grounded and safe talking to an employee," it's "does the system make a defensible, editable, auditable claim about what an SOP requires, and does it refuse to let that claim reach a live employee assessment without a human sign-off." That's the same fail-closed posture as the PII gate (§7) applied to graph authorship instead of personal data — nothing self-materializes without an explicit approval action.

### 8.5 Demo addition

A fourth, short demo beat (~1–2 min) alongside the three in §9, using the real corpus rather than a throwaway example: re-run the studio pipeline live on 2 of the actual `docs/sops/` files already behind the seed graph — `01-ppe-manual-handling.md` and `06-picking-packing-dg-coldchain.md` (chosen because the second one carries the limited-quantity/excepted-quantity misconception content called out in §5). Show the LLM-proposed taxonomy re-deriving the same `SAF.001`–`SAF.004` and `PRC.003`–`PRC.006` KCs the seed graph already has, then diverge from it on purpose: edit one node's name and redirect the `PRC.005 → SAF.001` `prerequisite_of` edge, click **Approve**, and show the resulting YAML is structurally identical in shape to the already-loaded seed graph — i.e. the runtime agent could load the edited version unmodified. The point of reusing real corpus files instead of a synthetic second role is to show the pipeline is reproducible against its own stated source (`docs/sops/README.md`'s expected-KC-coverage table), not just plausible-looking on a cherry-picked example.

---

## 9. Demo plan

Three conversations (~6 min total), detailed in VISION.md §14.3:

1. **Happy path** — Spanish, day-30 checkpoint: prior from Maria seeds mastery, assessment confirms and unlocks a KC, a failed item triggers grounded remediation with citation, mastery updates live, a personal fact is extracted, session emits summary + risk.
2. **Adversarial / edge cases** — mixed ES-RO: frustration triggers tone adaptation; a prompt-injection attempt is refused and logged; a health disclosure is acknowledged but not stored and routed to a human channel; an uncovered question causes abstain + gap flag; employee requests their memory view.
3. **Recertification nudge** — English, spoken read-back: TTS reads each reply back alongside the text, snooze honored and rescheduled.

Plus the KG-authoring beat in §8.5.

---

## 10. Time budget

~7.5h total, core requirements landing at ~5h (VISION.md §14.5): KG + items + SOP corpus (1.0h), conversation core (1.5h), mastery engine + tests (1.0h), extraction/PII gate/memory (1.0h), RAG + citations (0.5h), voice output (1.0h), tests/evals/README/demo (1.5h).

---

## 11. Open questions relevant to the build

- Voice: build on an existing telephony stack or a separate real-time provider? ASR accuracy in warehouse noise needs a spike before committing (non-blocking for the slice — mocked/simplified STT/TTS is acceptable).
- Does the item bank need per-language authoring vs. translate-and-review? For the slice, a small hand-authored ES/EN/RO set is sufficient.

Full open-questions list (legal, business-model, cross-agent contract ownership) is out of scope for the build and lives in VISION.md §15.
