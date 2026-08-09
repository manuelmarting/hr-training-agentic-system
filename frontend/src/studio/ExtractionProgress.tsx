// Live extraction progress (plan §4): renders the SSE event stream while the two-pass
// pipeline runs, so an 8-call corpus pass never looks like a frozen screen.

import type { ExtractionEvent } from "./api";

type Props = {
  events: ExtractionEvent[];
  running: boolean;
};

function line(event: ExtractionEvent): string {
  switch (event.type) {
    case "doc_started":
      return `Reading ${event.doc_id}…`;
    case "doc_done":
      return event.detail
        ? `${event.doc_id}: ${event.detail}`
        : `${event.doc_id} → ${event.kc_count} KC(s)`;
    case "reconciled":
      return `Reconciled to ${event.kc_count} unique KC(s)`;
    case "edges_started":
      return "Finding prerequisite edges across the corpus…";
    case "edges_done":
      return `${event.edge_count} edge(s) proposed`;
    case "validated":
      return `Validated — ${event.detail}`;
    case "done":
      return `Done: ${event.kc_count} KCs, ${event.edge_count} edges`;
    case "failed":
      return `Extraction failed: ${event.detail}`;
  }
}

export default function ExtractionProgress({ events, running }: Props) {
  return (
    <div className="extraction panel">
      <h3>
        {running ? <span className="spinner" aria-hidden /> : null}
        {running ? "Extracting graph…" : "Extraction finished"}
      </h3>
      <ol className="extraction-log">
        {events.map((event, i) => (
          <li key={i} className={event.type === "failed" ? "failed" : undefined}>
            {line(event)}
          </li>
        ))}
        {events.length === 0 && <li className="muted">Starting…</li>}
      </ol>
    </div>
  );
}
