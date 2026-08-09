// Node review panel (plan §6): a KC's attributes and its provenance excerpt are shown
// in the same view — never one without the other. The reviewer is always judging a claim
// against the source paragraph it came from.

import { useEffect, useState } from "react";
import type { Domain, KCPatch, ProposedKC } from "./api";

const DOMAINS: Domain[] = ["safety", "equipment", "process", "systems", "behavioural"];

type Props = {
  kc: ProposedKC;
  onSave: (patch: KCPatch) => void;
  onDelete: () => void;
  busy: boolean;
};

export default function NodeEditor({ kc, onSave, onDelete, busy }: Props) {
  const [name, setName] = useState(kc.name);
  const [domain, setDomain] = useState<Domain>(kc.domain);
  const [description, setDescription] = useState(kc.description);
  const [regulation, setRegulation] = useState(kc.regulation ?? "");
  const [supersededBy, setSupersededBy] = useState(kc.superseded_by_kc_id ?? "");
  const [misconceptions, setMisconceptions] = useState(kc.known_misconceptions.join("\n"));
  const [docId, setDocId] = useState(kc.provenance.doc_id);
  const [heading, setHeading] = useState(kc.provenance.heading);
  const [excerpt, setExcerpt] = useState(kc.provenance.excerpt);

  // Re-seed the form when a different node is selected.
  useEffect(() => {
    setName(kc.name);
    setDomain(kc.domain);
    setDescription(kc.description);
    setRegulation(kc.regulation ?? "");
    setSupersededBy(kc.superseded_by_kc_id ?? "");
    setMisconceptions(kc.known_misconceptions.join("\n"));
    setDocId(kc.provenance.doc_id);
    setHeading(kc.provenance.heading);
    setExcerpt(kc.provenance.excerpt);
  }, [kc]);

  function handleSave() {
    onSave({
      name,
      domain,
      description,
      regulation: regulation.trim() || null,
      superseded_by_kc_id: supersededBy.trim() || null,
      known_misconceptions: misconceptions
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean),
      provenance: { doc_id: docId, heading, excerpt },
    });
  }

  const provenanceMissing = !docId.trim() || !excerpt.trim();

  return (
    <div className="node-editor">
      <header className="node-editor__head">
        <h3>
          {kc.id}
          <span className={`origin-badge origin-badge--${kc.origin}`}>{kc.origin}</span>
        </h3>
        <button className="danger" onClick={onDelete} disabled={busy}>
          Delete node
        </button>
      </header>

      <label>
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>

      <label>
        Domain
        <select value={domain} onChange={(e) => setDomain(e.target.value as Domain)}>
          {DOMAINS.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </label>

      <label>
        Description
        <textarea
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </label>

      <div className="node-editor__row">
        <label>
          Regulation
          <input
            value={regulation}
            placeholder="e.g. ADR"
            onChange={(e) => setRegulation(e.target.value)}
          />
        </label>
        <label>
          Superseded by
          <input
            value={supersededBy}
            placeholder="KC id"
            onChange={(e) => setSupersededBy(e.target.value)}
          />
        </label>
      </div>

      <label>
        Known misconceptions (one per line)
        <textarea
          rows={2}
          value={misconceptions}
          onChange={(e) => setMisconceptions(e.target.value)}
        />
      </label>

      <section className={`provenance ${provenanceMissing ? "provenance--missing" : ""}`}>
        <h4>Provenance {provenanceMissing && <span>— required to approve</span>}</h4>
        <div className="node-editor__row">
          <label>
            Document
            <input value={docId} onChange={(e) => setDocId(e.target.value)} />
          </label>
          <label>
            Heading
            <input value={heading} onChange={(e) => setHeading(e.target.value)} />
          </label>
        </div>
        <label>
          Source excerpt
          <textarea
            rows={4}
            value={excerpt}
            placeholder="Paste the verbatim span this KC is drawn from"
            onChange={(e) => setExcerpt(e.target.value)}
          />
        </label>
      </section>

      <button className="primary" onClick={handleSave} disabled={busy}>
        Save changes
      </button>
    </div>
  );
}
