import type { Citation, ReasoningTrace as Trace, TraceStep } from "./api/chat";

type Props = {
  trace?: Trace;
  toolTrace: TraceStep[];
  citations: Citation[];
};

function formatArgs(args: Record<string, unknown>): string {
  const entries = Object.entries(args).filter(([, value]) => value !== "" && value != null);
  if (entries.length === 0) return "";
  return `(${entries.map(([key, value]) => `${key}=${JSON.stringify(value)}`).join(", ")})`;
}

/** Collapsed-by-default, greyed-out container above a Sofía reply (PRD §6.1/§7):
 * makes the assessment auditable without competing with the conversation. Shows
 * every tool the agent decided to call this turn, in order -- not just the
 * `evaluate_response` grading step, which additionally gets the structured summary
 * below (`trace`) since it's the one worth reading at a glance. */
export default function ReasoningTrace({ trace, toolTrace, citations }: Props) {
  return (
    <details className="reasoning-trace">
      <summary>Reasoning trace{trace ? ` (${trace.tool_call})` : ""}</summary>
      {trace && (
        <dl>
          <dt>KC</dt>
          <dd>{trace.kc_id}</dd>
          <dt>Classification</dt>
          <dd>{trace.classification}</dd>
          {trace.misconception_kc_id && (
            <>
              <dt>Misconception</dt>
              <dd>{trace.misconception_kc_id}</dd>
            </>
          )}
          <dt>Confidence</dt>
          <dd>{Math.round(trace.confidence * 100)}%</dd>
          <dt>Language / sentiment</dt>
          <dd>
            {trace.language} / {trace.sentiment}
          </dd>
          {trace.opt_out && (
            <>
              <dt>Opt-out</dt>
              <dd>detected</dd>
            </>
          )}
        </dl>
      )}
      {citations.length > 0 && (
        <ul className="reasoning-trace__citations">
          {citations.map((citation, index) => (
            <li key={index}>
              {citation.doc_id} — “{citation.heading}”
            </li>
          ))}
        </ul>
      )}
      {toolTrace.length > 0 && (
        <ol className="reasoning-trace__steps">
          {toolTrace.map((step, index) =>
            step.type === "thought" ? (
              <li key={index} className="reasoning-trace__step reasoning-trace__step--thought">
                {step.content}
              </li>
            ) : (
              <li key={index} className="reasoning-trace__step reasoning-trace__step--tool-call">
                <code>
                  {step.tool}
                  {formatArgs(step.args)}
                </code>{" "}
                → {step.result}
              </li>
            ),
          )}
        </ol>
      )}
    </details>
  );
}
