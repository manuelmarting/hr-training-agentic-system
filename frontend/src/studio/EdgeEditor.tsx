// Edge affordances (plan §6): add / remove prerequisite_of edges. Kept as an explicit
// picker rather than drag-to-create — simpler, and unambiguous about direction (source is
// the prerequisite; it must be mastered before the target).

import { useState } from "react";
import type { ProposedEdge, ProposedKC } from "./api";

type Props = {
  kcs: ProposedKC[];
  edges: ProposedEdge[];
  onAdd: (source: string, target: string, rationale: string) => void;
  onRemove: (source: string, target: string) => void;
  busy: boolean;
};

export default function EdgeEditor({ kcs, edges, onAdd, onRemove, busy }: Props) {
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [rationale, setRationale] = useState("");

  const canAdd = source && target && source !== target && !busy;

  return (
    <div className="edge-editor">
      <h4>Prerequisites ({edges.length})</h4>

      <ul className="edge-list">
        {edges.map((e) => (
          <li key={`${e.source_kc_id}->${e.target_kc_id}`}>
            <span>
              <strong>{e.source_kc_id}</strong> → {e.target_kc_id}
            </span>
            <button
              className="link-danger"
              onClick={() => onRemove(e.source_kc_id, e.target_kc_id)}
              disabled={busy}
            >
              remove
            </button>
          </li>
        ))}
        {edges.length === 0 && <li className="muted">none</li>}
      </ul>

      <div className="edge-editor__add">
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">prerequisite…</option>
          {kcs.map((kc) => (
            <option key={kc.id} value={kc.id}>
              {kc.id}
            </option>
          ))}
        </select>
        <span>→</span>
        <select value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">unlocks…</option>
          {kcs.map((kc) => (
            <option key={kc.id} value={kc.id}>
              {kc.id}
            </option>
          ))}
        </select>
        <input
          value={rationale}
          placeholder="rationale"
          onChange={(e) => setRationale(e.target.value)}
        />
        <button
          className="primary"
          disabled={!canAdd}
          onClick={() => {
            onAdd(source, target, rationale);
            setSource("");
            setTarget("");
            setRationale("");
          }}
        >
          Add
        </button>
      </div>
    </div>
  );
}
