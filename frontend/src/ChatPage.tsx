import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  streamChatReply,
  openSession,
  getKg,
  getKgForEmployee,
  getSessionFacts,
  getEmployeeFacts,
  type ChatMessage,
  type Citation,
  type KCInfo,
  type ReasoningTrace as Trace,
  type StoredFact,
} from "./api/chat";
import MasteryPanel from "./MasteryPanel";
import MemoryLog from "./MemoryLog";
import ReasoningTrace from "./ReasoningTrace";
import "./App.css";

type DisplayMessage = ChatMessage & {
  trace?: Trace;
  citations?: Citation[];
  system?: boolean;
  audioBlocked?: boolean;
};

const EMPLOYEE_ID_STORAGE_KEY = "sofia_employee_id";

export default function ChatPage() {
  // Manual per-browser identity (PRD non-goal: no real auth) -- entered once via
  // the gate screen below, then remembered so learner_model/personal_facts stay
  // keyed consistently to the same employee_id across reloads instead of every
  // session on this deployment landing on the same shared default.
  const [employeeId, setEmployeeId] = useState<string | null>(() =>
    localStorage.getItem(EMPLOYEE_ID_STORAGE_KEY),
  );
  const [employeeIdInput, setEmployeeIdInput] = useState("");
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [kcs, setKcs] = useState<KCInfo[]>([]);
  const [facts, setFacts] = useState<StoredFact[]>([]);

  // Buffered until the reply's first token arrives, then attached to that message
  // (PRD §6.1: reasoning container precedes the rendered reply).
  const pendingTrace = useRef<Trace | null>(null);
  const pendingCitations = useRef<Citation[]>([]);
  const sessionIdRef = useRef<string | null>(null);
  // Which message index the audio from the in-flight turn belongs to, and the
  // blocked Audio elements keyed by that index (not React state -- an
  // HTMLAudioElement doesn't need to trigger re-renders itself; only the
  // `audioBlocked` flag on the message does).
  const lastMessageIndexRef = useRef<number>(-1);
  const audioElementsRef = useRef<Record<number, HTMLAudioElement>>({});
  // React 18 StrictMode double-invokes effects in dev; without this guard the mount
  // effect below would open two sessions and show two welcome messages.
  const openedSessionRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  async function refreshPanels(id: string) {
    const [kg, sessionFacts] = await Promise.all([getKg(id), getSessionFacts(id)]);
    setKcs(kg);
    setFacts(sessionFacts);
  }

  // Facts/mastery are keyed by employee, not session -- load them straight from
  // the learner model as soon as the employee id is known, instead of waiting for
  // a session to open and its welcome turn to finish streaming.
  async function loadPanelsForEmployee(id: string) {
    const [kg, employeeFacts] = await Promise.all([getKgForEmployee(id), getEmployeeFacts(id)]);
    setKcs(kg);
    setFacts(employeeFacts);
  }

  // The "audio" SSE event arrives after all of the turn's "token" chunks (the
  // backend synthesizes speech from the fully-finalized reply text), so by the
  // time this fires the message is already on screen -- just play it.
  // Browsers require a recent user gesture to autoplay; a rejected play() (e.g.
  // the very first welcome message, one network round-trip removed from the
  // employee-ID gate click) falls back to a manual "Play audio" button on that
  // message instead of silently losing the audio.
  function playAudio(audioB64: string) {
    const audio = new Audio(`data:audio/wav;base64,${audioB64}`);
    const index = lastMessageIndexRef.current;
    audio.play().catch((error) => {
      console.warn("audio autoplay blocked", error);
      if (index < 0) return;
      audioElementsRef.current[index] = audio;
      setMessages((current) => {
        if (index >= current.length) return current;
        const updated = [...current];
        updated[index] = { ...updated[index], audioBlocked: true };
        return updated;
      });
    });
  }

  function handlePlayAudio(index: number) {
    const audio = audioElementsRef.current[index];
    if (!audio) return;
    delete audioElementsRef.current[index];
    audio.play().catch((error) => console.warn("manual audio play failed", error));
    setMessages((current) => {
      if (index >= current.length) return current;
      const updated = [...current];
      updated[index] = { ...updated[index], audioBlocked: false };
      return updated;
    });
  }

  useEffect(() => {
    if (!employeeId) return;
    void loadPanelsForEmployee(employeeId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employeeId]);

  useEffect(() => {
    if (!employeeId || openedSessionRef.current) return;
    openedSessionRef.current = true;

    let awaitingNewReply = true;
    void openSession({
      onChunk: (chunk) => {
        const isFirstChunk = awaitingNewReply;
        awaitingNewReply = false;
        setMessages((current) => {
          if (isFirstChunk) {
            lastMessageIndexRef.current = current.length;
            return [
              ...current,
              {
                role: "assistant",
                content: chunk,
                trace: pendingTrace.current ?? undefined,
                citations: pendingCitations.current,
              },
            ];
          }
          const updated = [...current];
          const last = updated[updated.length - 1];
          updated[updated.length - 1] = { ...last, content: last.content + chunk };
          return updated;
        });
      },
      onSession: (id) => {
        sessionIdRef.current = id;
        setSessionId(id);
      },
      onReasoning: (trace) => {
        pendingTrace.current = trace;
      },
      onCitation: (citation) => {
        pendingCitations.current = [...pendingCitations.current, citation];
      },
      onMastery: () => {
        if (sessionIdRef.current) void refreshPanels(sessionIdRef.current);
      },
      onMemoryEvent: () => {
        if (sessionIdRef.current) void refreshPanels(sessionIdRef.current);
      },
      onAudio: playAudio,
      onError: (message) => {
        setMessages((current) => [
          ...current,
          { role: "assistant", content: message, system: true },
        ]);
      },
    }, employeeId)
      .then(() => {
        // The welcome turn never calls evaluate_response/extract_facts (there's
        // nothing to grade yet), so onMastery/onMemoryEvent never fire for it --
        // without this, the panels would stay empty until the employee's first
        // real answer even though their prior mastery/facts are already loaded
        // into the session's checkpoint by the time this turn finishes.
        if (sessionIdRef.current) void refreshPanels(sessionIdRef.current);
      })
      .catch((error) => {
        console.error("session open failed", error);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employeeId]);

  function handleEmployeeIdSubmit(event: FormEvent) {
    event.preventDefault();
    const id = employeeIdInput.trim();
    if (!id) return;
    localStorage.setItem(EMPLOYEE_ID_STORAGE_KEY, id);
    setEmployeeId(id);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || isStreaming) return;

    const userMessage: DisplayMessage = { role: "user", content: text };
    const nextMessages: DisplayMessage[] = [...messages, userMessage];
    setMessages(nextMessages);
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    setIsStreaming(true);

    pendingTrace.current = null;
    pendingCitations.current = [];
    let awaitingNewReply = true;

    try {
      await streamChatReply(nextMessages, sessionId, {
        onChunk: (chunk) => {
          // Capture and flip the turn-boundary flag here, outside the updater: React
          // 18 StrictMode invokes setState updaters twice in dev to catch impurities,
          // discarding the first result. Mutating `awaitingNewReply` *inside* the
          // updater made call 2 see it already flipped by call 1, so it took the
          // "append" branch against the stale `current` (still ending in the user's
          // message) and glued the reply onto the user's bubble instead of pushing a
          // new assistant one.
          const isFirstChunk = awaitingNewReply;
          awaitingNewReply = false;
          setMessages((current) => {
            if (isFirstChunk) {
              lastMessageIndexRef.current = current.length;
              return [
                ...current,
                {
                  role: "assistant",
                  content: chunk,
                  trace: pendingTrace.current ?? undefined,
                  citations: pendingCitations.current,
                },
              ];
            }
            const updated = [...current];
            const last = updated[updated.length - 1];
            updated[updated.length - 1] = { ...last, content: last.content + chunk };
            return updated;
          });
        },
        onSession: (id) => {
          // Don't refresh panels here: for a brand-new session the graph hasn't run
          // its first node yet, so no checkpoint exists — GET /facts 404s every time.
          // `onMastery` re-triggers this moments later once `update` has actually
          // written a checkpoint, which covers every turn (it runs unconditionally).
          sessionIdRef.current = id;
          setSessionId(id);
        },
        onReasoning: (trace) => {
          pendingTrace.current = trace;
        },
        onCitation: (citation) => {
          pendingCitations.current = [...pendingCitations.current, citation];
        },
        onMastery: () => {
          // Refetched rather than patched locally: gating depends on the full
          // mastery dict server-side, so a single KC's update can unlock others.
          if (sessionIdRef.current) void refreshPanels(sessionIdRef.current);
        },
        onMemoryEvent: () => {
          if (sessionIdRef.current) void refreshPanels(sessionIdRef.current);
        },
        onAudio: playAudio,
        onSessionStop: () => {
          setMessages((current) => [
            ...current,
            {
              role: "assistant",
              content: "Session paused at your request.",
              trace: pendingTrace.current ?? undefined,
              citations: pendingCitations.current,
              system: true,
            },
          ]);
          awaitingNewReply = false;
        },
        onError: (message) => {
          setMessages((current) => [
            ...current,
            { role: "assistant", content: message, system: true },
          ]);
          awaitingNewReply = false;
        },
      }, false, employeeId ?? undefined);
    } catch (error) {
      console.error("chat stream failed", error);
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: "Something went wrong sending that message. Please try again.",
          system: true,
        },
      ]);
    } finally {
      setIsStreaming(false);
    }
  }

  if (!employeeId) {
    return (
      <div className="employee-gate">
        <form className="employee-gate__form" onSubmit={handleEmployeeIdSubmit}>
          <h1>Sofía</h1>
          <p>Enter your employee ID to start your training session.</p>
          <input
            type="text"
            value={employeeIdInput}
            onChange={(event) => setEmployeeIdInput(event.target.value)}
            placeholder="Employee ID"
            autoFocus
          />
          <button type="submit" disabled={!employeeIdInput.trim()}>
            Start
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="layout">
      <MemoryLog
        facts={facts}
        onDeleted={(factId) => setFacts((current) => current.filter((f) => f.id !== factId))}
      />

      <div className="chat">
        <h1>
          Sofía<span className="chat-title__divider">·</span>
          <span className="chat-title__studio">Chat Studio</span>
          <a href="/studio" className="chat__studio-link">KG Studio →</a>
        </h1>
        <div className="chat-messages">
          {messages.map((message, index) => (
            <div key={index} className={`chat-message-row chat-message-row--${message.role}`}>
              {message.trace && (
                <ReasoningTrace trace={message.trace} citations={message.citations ?? []} />
              )}
              <div
                className={`chat-message chat-message--${message.role}${
                  message.system ? " chat-message--system" : ""
                }`}
              >
                <span className="chat-message__role">
                  {message.role === "assistant" ? "Sofía" : "You"}
                </span>
                {message.content && <p>{message.content}</p>}
                {message.audioBlocked && (
                  <button
                    type="button"
                    className="chat-message__play-audio"
                    onClick={() => handlePlayAudio(index)}
                  >
                    ▶ Play audio
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
        <form className="chat-input" onSubmit={handleSubmit}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(event) => {
              setInput(event.target.value);
              const el = event.target;
              el.style.height = "auto";
              el.style.height = `${el.scrollHeight}px`;
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="Ask about your HR training..."
            disabled={isStreaming}
            rows={1}
          />
          <button type="submit" disabled={isStreaming || !input.trim()}>
            Send
          </button>
        </form>
      </div>

      <MasteryPanel kcs={kcs} />
    </div>
  );
}
