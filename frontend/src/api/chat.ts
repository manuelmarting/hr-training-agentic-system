export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export type ReasoningTrace = {
  tool_call: string;
  kc_id: string;
  classification: string;
  misconception_kc_id: string | null;
  confidence: number;
  language: string;
  sentiment: string;
  opt_out: boolean;
};

/** The full session mastery dict as of this turn ({kc_id: posterior}), not a
 * single-KC delta — that's what `update["mastery"]` holds server-side. */
export type MasteryUpdate = Record<string, number>;

export type Citation = {
  doc_id: string;
  heading: string;
  excerpt: string;
};

export type MemoryFact = {
  fact_type: string;
  value: string;
  confidence: number;
};

export type ChatStreamHandlers = {
  onChunk: (text: string) => void;
  /** Fired once per turn with the session/thread id — echo it back on the next
   * call so the backend resumes the same graph session (plan §5) instead of
   * starting a fresh one every turn. */
  onSession?: (sessionId: string) => void;
  onReasoning?: (trace: ReasoningTrace) => void;
  onMastery?: (update: MasteryUpdate) => void;
  onCitation?: (citation: Citation) => void;
  onMemoryEvent?: (fact: MemoryFact) => void;
  onSessionStop?: () => void;
  onError?: (message: string) => void;
  /** Base64-encoded WAV audio for the turn's finalized reply, from the Kokoro
   * voice-service (backend/app/agent/tts.py). Omitted entirely when the voice
   * service is unavailable — text chat always works without it. */
  onAudio?: (audioB64: string) => void;
};

/**
 * Streams a chat reply via SSE. Uses fetch (not EventSource) because the
 * request needs a JSON body; parses the "event: ...\ndata: ...\n\n" frames
 * emitted by sse-starlette on the backend. Event names match the backend's
 * vocabulary (plan §5): "session", "token", "reasoning", "mastery_update",
 * "citation", "memory_event", "audio", "session_stop", "done".
 */
export async function streamChatReply(
  messages: ChatMessage[],
  sessionId: string | null,
  handlers: ChatStreamHandlers,
  isSessionOpen = false,
  employeeId?: string,
): Promise<void> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: messages.map(({ role, content }) => ({ role, content })),
      session_id: sessionId ?? undefined,
      is_session_open: isSessionOpen,
      employee_id: employeeId || undefined,
    }),
  });

  if (!response.body) {
    throw new Error("No response body for chat stream");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    // sse-starlette's default line separator is "\r\n" (frames end in "\r\n\r\n"),
    // not the bare "\n" this parser used to assume — normalize before splitting.
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      let event: string | undefined;
      // Per the SSE spec, a multi-line data payload arrives as multiple `data:`
      // lines that must be rejoined with "\n" to reconstruct the original value.
      const dataLines: string[] = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) {
          event = line.slice("event:".length).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice("data:".length).replace(/^ /, ""));
        }
      }
      const data = dataLines.join("\n");

      switch (event) {
        case "done":
          return;
        case "token":
          handlers.onChunk(data);
          break;
        case "session":
          handlers.onSession?.(JSON.parse(data).session_id);
          break;
        case "reasoning":
          handlers.onReasoning?.(JSON.parse(data));
          break;
        case "mastery_update":
          handlers.onMastery?.(JSON.parse(data));
          break;
        case "citation":
          handlers.onCitation?.(JSON.parse(data));
          break;
        case "memory_event":
          handlers.onMemoryEvent?.(JSON.parse(data));
          break;
        case "audio":
          handlers.onAudio?.(JSON.parse(data).audio_b64);
          break;
        case "session_stop":
          handlers.onSessionStop?.();
          break;
        case "error":
          handlers.onError?.(JSON.parse(data).message);
          break;
      }
    }
  }
}

/** Opens a brand-new session: no employee message yet, Sofía speaks first. Reuses
 * `streamChatReply`'s SSE parsing/handlers so the welcome lands the same way a
 * normal reply would. */
export async function openSession(handlers: ChatStreamHandlers, employeeId: string): Promise<void> {
  await streamChatReply([], null, handlers, true, employeeId);
}

// --- panel data (mastery panel + memory log) ---------------------------------

export type KCInfo = {
  id: string;
  name: string;
  domain: string;
  description: string;
  prerequisites: string[];
  gated: boolean;
  mastery: number | null;
};

export async function getKg(sessionId: string): Promise<KCInfo[]> {
  const res = await fetch(`/api/kg?session_id=${encodeURIComponent(sessionId)}`);
  if (!res.ok) throw new Error(`GET /api/kg failed: ${res.status}`);
  return res.json();
}

/** Reads mastery straight from the learner model by employee, not session --
 * for populating the panel on page load, before any session/checkpoint exists. */
export async function getKgForEmployee(employeeId: string): Promise<KCInfo[]> {
  const res = await fetch(`/api/kg?employee_id=${encodeURIComponent(employeeId)}`);
  if (!res.ok) throw new Error(`GET /api/kg failed: ${res.status}`);
  return res.json();
}

export type StoredFact = {
  id: number;
  employee_id: string;
  fact: MemoryFact;
  created_at: string;
};

export async function getSessionFacts(sessionId: string): Promise<StoredFact[]> {
  const res = await fetch(`/api/session/${encodeURIComponent(sessionId)}/facts`);
  if (!res.ok) throw new Error(`GET /api/session/${sessionId}/facts failed: ${res.status}`);
  return res.json();
}

/** For populating the memory log on page load, before any session/checkpoint
 * exists -- facts are keyed by employee, not session. */
export async function getEmployeeFacts(employeeId: string): Promise<StoredFact[]> {
  const res = await fetch(`/api/employee/${encodeURIComponent(employeeId)}/facts`);
  if (!res.ok) throw new Error(`GET /api/employee/${employeeId}/facts failed: ${res.status}`);
  return res.json();
}

export async function deleteFact(factId: number): Promise<void> {
  const res = await fetch(`/api/facts/${factId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`DELETE /api/facts/${factId} failed: ${res.status}`);
}
