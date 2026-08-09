// "Seed from SOPs" panel (user request): the committed SOP corpus is pre-loaded and
// pre-selected (removable), and the reviewer can add their own files. Submitting kicks off
// LLM extraction over the chosen set.

import { useEffect, useRef, useState } from "react";
import * as api from "./api";
import type { SopDoc } from "./api";

type Props = {
  busy: boolean;
  onCreate: (sopIds: string[], files: File[]) => void;
  onCancel: () => void;
};

export default function SopUploader({ busy, onCreate, onCancel }: Props) {
  const [sops, setSops] = useState<SopDoc[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .listSops()
      .then((docs) => {
        setSops(docs);
        setSelected(new Set(docs.map((d) => d.doc_id))); // pre-select all by default
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function addFiles(list: FileList | null) {
    if (!list) return;
    setFiles((current) => [...current, ...Array.from(list)]);
    if (fileInput.current) fileInput.current.value = "";
  }

  const total = selected.size + files.length;

  return (
    <div className="sop-uploader panel">
      <div className="sop-uploader__head">
        <h3>Seed from SOPs</h3>
        <button className="link" onClick={onCancel} disabled={busy}>
          cancel
        </button>
      </div>
      <p className="muted">
        The eight committed SOPs are loaded and selected by default. Deselect any, or add your
        own documents (.md, .txt, .pdf). An LLM proposes the knowledge graph from the set.
      </p>

      {error && <div className="studio__error">{error}</div>}

      <h4 className="sec">Committed corpus</h4>
      <ul className="sop-list">
        {sops.map((doc) => (
          <li key={doc.doc_id}>
            <label>
              <input
                type="checkbox"
                checked={selected.has(doc.doc_id)}
                onChange={() => toggle(doc.doc_id)}
                disabled={busy}
              />
              <span className="sop-name">{doc.filename}</span>
              <span className="sop-size">{(doc.chars / 1000).toFixed(1)}k</span>
            </label>
          </li>
        ))}
      </ul>

      <h4 className="sec">Your uploads ({files.length})</h4>
      {files.length > 0 && (
        <ul className="sop-list">
          {files.map((file, i) => (
            <li key={`${file.name}-${i}`}>
              <span className="sop-name">{file.name}</span>
              <button
                className="link-danger"
                onClick={() => setFiles((c) => c.filter((_, j) => j !== i))}
                disabled={busy}
              >
                remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <input
        ref={fileInput}
        type="file"
        multiple
        accept=".md,.markdown,.txt,.pdf"
        onChange={(e) => addFiles(e.target.files)}
        disabled={busy}
      />

      <button
        className="primary"
        disabled={busy || total === 0}
        onClick={() => onCreate([...selected], files)}
      >
        {busy ? "Extracting…" : `Create graph from ${total} document${total === 1 ? "" : "s"}`}
      </button>
    </div>
  );
}
