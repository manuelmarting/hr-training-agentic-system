import type { Citation, ReasoningTrace as Trace } from "./api/chat";

type Props = {
  trace: Trace;
  citations: Citation[];
};

/** Collapsed-by-default, greyed-out container above a Sofía reply (PRD §6.1/§7):
 * makes the assessment auditable without competing with the conversation. */
export default function ReasoningTrace({ trace, citations }: Props) {
  return (
    <details className="reasoning-trace">
      <summary>Reasoning trace ({trace.tool_call})</summary>
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
      {citations.length > 0 && (
        <ul className="reasoning-trace__citations">
          {citations.map((citation, index) => (
            <li key={index}>
              {citation.doc_id} — “{citation.heading}”
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
