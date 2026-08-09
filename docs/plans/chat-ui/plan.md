# Plan — Workflow 3: Chat UI and Adjacent Panels

**Scope:** PRD §6.1 (chat UI rows) and §7 (layout / mastery panel / transparency requirements). The three-column demo surface: memory-extraction log (left), Sofía conversation with per-turn reasoning traces (center), live BKT mastery panel (right).

**Depends on:** [workflow 1](../conversational-agent/plan.md) for the SSE event contract and REST snapshots. Shares the app shell and design tokens with [workflow 2](../kg-studio/plan.md).

**Status:** phases 1–6 implemented, phase 7 partial. Shipped: `ChatPage.tsx` (conversation + composer + reasoning traces), `MasteryPanel.tsx`, `MemoryLog.tsx` (with per-fact delete via `DELETE /api/facts/{id}`), `ReasoningTrace.tsx`, `api/chat.ts` (typed SSE dispatcher + REST helpers), plus the full `studio/` route (`StudioPage.tsx`, `GraphCanvas.tsx`, `NodeEditor.tsx`, `EdgeEditor.tsx`, `SopUploader.tsx`, `ExtractionProgress.tsx`, `ApproveBar.tsx`). Structurally this is flatter than §3's proposed `chat/`/`panels/` subfolders — components sit directly under `frontend/src/` — no `app/` folder, no `useSession.ts` reducer; state is plain `useState` calls inside `ChatPage.tsx`. Routing is **path-based** (`App.tsx` switches on `window.location.pathname.startsWith("/studio")`, with an explicit FastAPI `/studio` SPA-fallback route in `app/main.py`), not the hash-based `#/` scheme in §1/§3 — same "no router dependency" commitment, different mechanism. The app runs on **React 19** (`package.json`), not React 18 as originally written; no other design commitment in §1 depended on the major version. **Not built:** the channel toggle and the escalation banner (§5's "Escalation" and "Channel toggle" behaviors), the mastery panel's per-turn delta/lock-reason/animation, and the memory log's rejected-fact rendering and "what Sofía remembers" drawer — these are all still described below as shipped design but are aspirational; see the corrected behavior notes in §3–§5. No `vitest`/reducer test exists (§8) — there is no telegram/voice switch in the UI, no `EscalationBanner.tsx`, and no test runner in `frontend/` at all, consistent with the backend's safety-interrupt path also not being built (see workflow 1's plan). **Two shipped features not in this plan at all:** an employee-ID entry gate (`ChatPage.tsx`, localStorage-persisted identity, shown before the chat mounts) and best-effort TTS audio playback (`onAudio`/`playAudio`, backed by `backend/app/agent/tts.py` Kokoro, with an autoplay-blocked fallback button) driven by an `audio` SSE event. The actual SSE event set is `session, token, reasoning, mastery_update, citation, memory_event, audio, session_stop, error, done` — see the corrected §4.

---

## 1. Design commitments

| Decision | Choice | Why |
|---|---|---|
| State | `useReducer` over one `SessionState` object, fed by the SSE stream — **as designed; as built, `ChatPage.tsx` uses plain `useState` calls and no reducer exists** | Every panel is a projection of one server-derived state. Multiple `useState` islands is how the panels drift out of sync |
| No client-side computation | Panels render server numbers only | PRD §7: the panel is "a live view onto the mastery engine's state, not a separate mock" |
| Dependencies | None added | React 19 + TS + Vite is enough. No component library, no chart library, no state library, no router library (see below) |
| Routing | A path-based switch on `window.location.pathname` (`/` chat, `/studio`), with a FastAPI SPA-fallback route for deep links — shipped this way rather than the hash-based `#/` sketched originally | Two routes. `react-router` is a dependency for a switch statement |
| Streaming | Extend the existing `fetch` + SSE-frame parser in `api/chat.ts` | Already written and works; it just needs typed multi-event dispatch |
| Layout | CSS grid, full viewport height, three columns collapsing to tabs under ~1100px | PRD §7 requires full-height with a reserved right margin |

**Invariant:** the mastery panel and memory log never derive values. If a number isn't in an event or a snapshot response, it isn't rendered.

---

## 2. Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  Sofía · warehouse_operative · session #a1b2      [chat] [studio]    │
├───────────────┬──────────────────────────────┬───────────────────────┤
│ MEMORY        │  conversation (scrolls)      │  MASTERY              │
│ EXTRACTION    │                              │                       │
│               │  ┌ Ana ───────────────────┐  │  SAF.001  ▓▓▓▓▓░ 0.78 │
│ 14:02 ✓ shift │  │ [photo]                │  │     ↑ +0.12 this turn │
│    preference │  │ "así se coloca?"       │  │                       │
│ 14:03 ✗ health│  └────────────────────────┘  │  PRC.005  ▓▓░░░░ 0.31 │
│    → rejected │                              │     locked · needs    │
│    (special   │  ▸ reasoning · 3 tool calls  │       SAF.001         │
│     category) │  ┌ Sofía ─────────────────┐  │                       │
│ 14:05 ✓ prior │  │ reply text…            │  │  ── citations ──      │
│    site       │  │ 📎 SOP-PRC-02 §3.2     │  │  SOP-PRC-02 §3.2      │
│               │  └────────────────────────┘  │                       │
├───────────────┴──────────────────────────────┴───────────────────────┤
│  [ text input ]                          channel: (telegram | voice) │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component layout

**As originally sketched** (superseded — kept for the rationale, not as current structure):

```
frontend/src/
  app/
    AppShell.tsx        # grid, header, hash route switch
    routes.ts
  chat/
    ChatPage.tsx        # owns useSessionReducer, wires the stream
    useSession.ts       # reducer + SSE subscription hook
    Conversation.tsx
    MessageBubble.tsx   # WhatsApp-style; inline photo inset for employee turns
    ReasoningTrace.tsx  # collapsed grey container: reasoning + tool calls
    Composer.tsx        # input, channel toggle, send/retry
  panels/
    MasteryPanel.tsx    # KC list, probability bars, per-turn delta, lock reason
    MemoryLog.tsx       # streamed PersonalFact accept/reject lines
    CitationList.tsx
    EscalationBanner.tsx
  api/
    stream.ts           # typed SSE dispatcher (generalizes today's chat.ts)
    types.ts            # hand-mirrored event models from events/schemas.py
    session.ts          # REST: mastery snapshot, facts list/delete, KG metadata
  styles/tokens.css     # colors (incl. 5 domain hues), spacing, type scale
```

**As built:** flat, no subfolders, no reducer.

```
frontend/src/
  App.tsx              # path-based switch: "/" -> ChatPage, "/studio" -> StudioPage
  ChatPage.tsx          # owns plain useState state, employee-ID gate, SSE wiring,
                        # conversation, composer, audio playback
  MasteryPanel.tsx      # KC list + probability bars, no delta/lock-reason/animation
  MemoryLog.tsx         # accepted-fact list with per-item delete; no rejections shown
  ReasoningTrace.tsx    # collapsed container rendering the structured TurnEvaluation
  api/chat.ts           # typed SSE dispatcher + REST helpers (kept as-is, not split
                        # into stream.ts/types.ts/session.ts)
  App.css, theme.css    # design tokens
  studio/               # workflow 2's route, unchanged from this plan's expectations
```

Panel/log/trace responsibilities are the same as described below in spirit, but several behaviors listed in §5 (delta fade, lock reasons, bar animation, rejected-fact rendering, the memory drawer) were never implemented — see the corrected notes inline in §5.

---

## 4. Event contract (client side)

**As originally sketched** (superseded — see below for the real contract):

```ts
type ServerEvent =
  | { type: "token";         text: string }
  | { type: "reasoning";     turnId: string; text: string }
  | { type: "tool_call";     turnId: string; name: string; args: Record<string, unknown> }
  | { type: "mastery_update"; kcId: string; probability: number; delta: number; turnId: string }
  | { type: "memory_event";  status: "stored" | "rejected"; factType: string;
                             reason?: string; at: string }
  | { type: "citation";      docId: string; heading: string }
  | { type: "escalation";    reason: string }
  | { type: "kc_selected";   kcId: string; lockedBy: string[] }
  | { type: "error";         message: string; recoverable: boolean }
  | { type: "done" };
```

**As built** (`frontend/src/api/chat.ts`) — no `tool_call`, `kc_selected`, or `escalation` event exists; `mastery_update` carries the full posterior dict rather than a per-KC delta, and there's an `audio`/`session_stop` pair the sketch never anticipated:

```ts
type ServerEvent =
  | { type: "session";        session_id: string }
  | { type: "token";          text: string }
  | { type: "reasoning";      /* structured TurnEvaluation: tool_call name, kc_id,
                                  classification, misconception_kc_id, confidence,
                                  language, sentiment, opt_out */ }
  | { type: "mastery_update"; mastery: Record<string, number> } // {kc_id: posterior}, full dict
  | { type: "citation";       docId: string; heading: string }
  | { type: "memory_event";   /* payload discarded client-side; triggers a full
                                  refetch of facts via refreshPanels() */ }
  | { type: "audio";          /* base64 TTS audio, best-effort Kokoro */ }
  | { type: "session_stop" }
  | { type: "error";          message: string }
  | { type: "done" };
```

There is no hand-mirrored `types.ts` and no contract fixture test (§7/§8's plan for one was never built) — drift between backend Pydantic models and this union is currently caught only by manual testing.

---

## 5. Panel behaviors

### Mastery panel

*As designed* (not built): per-row signed delta fading after ~3s, domain color, an explicit "needs `SAF.001`" lock reason, CSS bar-change animation.

*As built* (`MasteryPanel.tsx`): name, percent, a static-width bar; gated KCs render the literal string "locked" with no reason, no domain color, no delta, no animation. `mastery_update` delivers the full `{kc_id: posterior}` dict and the panel is refetched wholesale via `refreshPanels()` rather than applying incremental deltas. Hydration on load/reload works as designed.

### Memory extraction log

*As designed* (not built): rejected facts rendered with a cross + gate reason ("special category — not stored"), and a collapsible "what Sofía remembers" drawer.

*As built* (`MemoryLog.tsx`): lists only accepted `StoredFact`s from `GET /api/session/{id}/facts`, always visible (not a drawer), each with a delete `×` button (`DELETE /api/facts/{id}`). There is no rendering path for rejected facts anywhere in the frontend — `memory_event` payloads are discarded; the handler just triggers a full refetch. This is a real gap against the "fail-closed PII gate visible" goal (§0/PRD §7), not just a naming difference — rejections happen server-side but are invisible in the UI.

### Reasoning trace
- One collapsed `<details>`-style container immediately above each Sofía reply, greyed, showing the turn's reasoning text and tool calls (`name` + key args). Collapsed by default, always present.
- Streams open-able while the turn is still in flight so the demo shows work happening, not a post-hoc reveal.

### Message bubbles
- Employee turns right-aligned with rounded bubble; an attached profile photo renders inset at the top of the bubble with text beneath (WhatsApp style). **Not built** — `ChatPage.tsx` renders plain text bubbles only, no photo inset.
- Agent turns are labeled **Sofía** throughout — no "assistant"/"bot" string anywhere in the UI, including `aria-label`s.
- Citations render as a footer chip on the message that carries them.

### Escalation
- On `escalation`, a banner takes over the composer: the session is suspended, input disabled, handoff message shown. No way to keep typing — the UI enforces the same fail-closed posture as the backend.

### Channel toggle
- Switching to `voice` re-renders in voice-policy mode (short turns, no markdown, spoken digit confirmations shown as text) so the channel-adaptive policy is visible in one surface.

---

## 6. Error and loading states

Required by CLAUDE.md ("an assessment session must not silently hang"):
- Stream connection failure → visible error row + Retry that resumes the same `session_id`.
- Mid-stream drop → partial reply is kept, marked incomplete, retry offered.
- Per-turn thinking indicator while no token has arrived.
- Panel hydration failures render an inline "couldn't load mastery" state, never an empty panel that reads as "no mastery".

---

## 7. Build phases

1. **Shell + tokens + hash routing.** Three-column grid, full-height, responsive collapse. Stub panels with fixture data.
2. **Typed stream layer.** Generalize `api/chat.ts` into `stream.ts` with the discriminated union above; keep the existing frame parser.
3. **`useSession` reducer.** One state object; unit-test the reducer with a recorded event sequence (pure function, no DOM).
4. **Conversation column**: bubbles, photo inset, reasoning trace, citations, Sofía labeling.
5. **Mastery panel** wired to `mastery_update` + snapshot hydration, with lock reasons.
6. **Memory log + drawer** including delete.
7. **Escalation, errors, channel toggle.**
8. **Studio route** mounts into the same shell ([workflow 2](../kg-studio/plan.md) owns its internals).

Phases 1–5 are the demo-critical path.

---

## 8. Tests

There is no test runner in `frontend/` today. Adding one (`vitest`) is justified for exactly one thing: the reducer.

| Area | Test |
|---|---|
| Reducer | recorded event sequence → expected final state; out-of-order and duplicate `mastery_update` handled |
| Contract | a fixture JSON exported from the backend's Pydantic models parses into `ServerEvent` without `any` — catches drift |
| Type safety | `npm run build` (`tsc -b`) stays green; no `any` |
| Lint | `npm run lint` green (`react-hooks`, `react-refresh`) |

If vitest is judged out of budget, the reducer test moves to a backend-side fixture check and the reducer stays trivially pure — but the reducer must remain pure either way.

---

## 9. Risks

- **Panel/backend drift** — the hand-mirrored types are the weak point. The contract fixture test in §7 is the mitigation and should land with phase 2, not later.
- **Three columns on a laptop screen** during a live demo. Mitigation: design at 1440px, collapse to tabs below 1100px, and verify at the actual demo resolution before recording.
- **Reasoning traces stealing attention** — must be collapsed and low-contrast by default (PRD §7 says so explicitly); resist making them look interesting.

---

## 10. Done

A full-height three-column surface where, during one live conversation, mastery bars move per turn with visible deltas and lock reasons, extracted facts stream in (including a visible rejection), each Sofía turn carries an expandable reasoning trace, citations are attached to remediation, and an escalation hard-stops the session.
