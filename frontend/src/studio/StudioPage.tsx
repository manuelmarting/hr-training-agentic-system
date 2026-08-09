// Studio route shell (plan §6): upload/seed/extract → review canvas + editors → approve.
// A second route in the same app (not a separate app, PRD §8.2). "Seed from SOPs" runs LLM
// extraction over the committed corpus + uploaded files, streaming progress over SSE.
// Mastery/graph state is always the backend's — the UI never fabricates it.

import { useCallback, useMemo, useState } from "react";
import * as api from "./api";
import type {
  ExtractionEvent,
  GraphDraft,
  ProposedKC,
  ValidationIssue,
  ValidationResult,
} from "./api";
import ApproveBar from "./ApproveBar";
import EdgeEditor from "./EdgeEditor";
import ExtractionProgress from "./ExtractionProgress";
import GraphCanvas from "./GraphCanvas";
import NodeEditor from "./NodeEditor";
import SopUploader from "./SopUploader";
import "./studio.css";

export default function StudioPage() {
  const [draft, setDraft] = useState<GraphDraft | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [approvedYaml, setApprovedYaml] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploaderOpen, setUploaderOpen] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [progress, setProgress] = useState<ExtractionEvent[]>([]);

  const refreshValidation = useCallback(async (id: string) => {
    setValidation(await api.getValidation(id));
  }, []);

  const run = useCallback(
    async (fn: () => Promise<GraphDraft>) => {
      setBusy(true);
      setError(null);
      try {
        const next = await fn();
        setDraft(next);
        await refreshValidation(next.draft_id);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [refreshValidation],
  );

  async function create(seed: boolean) {
    setUploaderOpen(false);
    setApprovedYaml(null);
    setSelectedId(null);
    await run(() => api.createDraft("warehouse_operative", seed));
  }

  function openUploader() {
    setUploaderOpen(true);
    setDraft(null);
    setValidation(null);
    setApprovedYaml(null);
    setSelectedId(null);
    setError(null);
    setProgress([]);
  }

  async function startExtraction(sopIds: string[], files: File[]) {
    setApprovedYaml(null);
    setSelectedId(null);
    setValidation(null);
    setProgress([]);
    setError(null);
    setExtracting(true);
    try {
      const created = await api.createDraftFromSops("warehouse_operative", sopIds, files);
      setDraft(created); // status: extracting
      setUploaderOpen(false);
      const es = api.openExtractionStream(created.draft_id, {
        onProgress: (event) => {
          setProgress((current) => [...current, event]);
          if (event.type === "failed") setError(event.detail);
        },
        onEnd: async () => {
          es.close();
          const full = await api.getDraft(created.draft_id);
          setDraft(full);
          if (full.status !== "failed") await refreshValidation(full.draft_id);
          setExtracting(false);
        },
        onError: () => {
          es.close();
          setExtracting(false);
        },
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setExtracting(false);
    }
  }

  const highlightIds = useMemo(() => {
    const ids = new Set<string>();
    for (const issue of validation?.issues ?? []) {
      if (issue.kc_id) ids.add(issue.kc_id);
      if (issue.edge) issue.edge.forEach((e) => ids.add(e));
    }
    return ids;
  }, [validation]);

  const selected: ProposedKC | null =
    draft?.kcs.find((kc) => kc.id === selectedId) ?? null;

  function focusIssue(issue: ValidationIssue) {
    if (issue.kc_id) setSelectedId(issue.kc_id);
    else if (issue.edge) setSelectedId(issue.edge[1]);
  }

  async function approve() {
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.approveDraft(draft.draft_id);
      setApprovedYaml(res.yaml);
      setDraft(await api.getDraft(draft.draft_id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      if (draft) await refreshValidation(draft.draft_id);
    } finally {
      setBusy(false);
    }
  }

  const approved = draft?.status === "approved";

  return (
    <div className="studio">
      <header className="studio__header">
        <h1>KG Authoring Studio</h1>
        <nav>
          <a href="/">← chat</a>
        </nav>
      </header>

      <div className="studio__toolbar">
        <button className="primary" onClick={openUploader} disabled={busy || extracting}>
          Seed from SOPs
        </button>
        <button onClick={() => create(true)} disabled={busy || extracting}>
          Seed from committed graph
        </button>
        <button onClick={() => create(false)} disabled={busy || extracting}>
          New empty draft
        </button>
        {draft && (
          <span className="draft-id">
            draft <code>{draft.draft_id.slice(0, 8)}</code> · {draft.status} ·{" "}
            {draft.kcs.length} KCs
          </span>
        )}
      </div>

      {error && <div className="studio__error">{error}</div>}

      {uploaderOpen && (
        <SopUploader busy={extracting} onCreate={startExtraction} onCancel={() => setUploaderOpen(false)} />
      )}

      {!draft && !uploaderOpen && (
        <p className="studio-empty">
          <strong>Seed from SOPs</strong> to build a graph from uploaded documents, seed from
          the committed graph to review the existing 25-KC graph, or start an empty draft.
        </p>
      )}

      {draft && (extracting || draft.status === "extracting") && (
        <ExtractionProgress events={progress} running={extracting} />
      )}

      {draft && !extracting && draft.status !== "extracting" && (
        <div className="studio__body">
          <div className="studio__left">
            <GraphCanvas
              kcs={draft.kcs}
              edges={draft.edges}
              selectedId={selectedId}
              highlightIds={highlightIds}
              onSelect={setSelectedId}
            />
            <AddNodeForm
              disabled={busy}
              existingIds={draft.kcs.map((k) => k.id)}
              onAdd={(kc) => run(() => api.addKC(draft.draft_id, kc))}
            />
            <EdgeEditor
              kcs={draft.kcs}
              edges={draft.edges}
              busy={busy}
              onAdd={(s, t, r) => run(() => api.addEdge(draft.draft_id, s, t, r))}
              onRemove={(s, t) => run(() => api.deleteEdge(draft.draft_id, s, t))}
            />
          </div>

          <div className="studio__right">
            {selected ? (
              <NodeEditor
                key={selected.id}
                kc={selected}
                busy={busy}
                onSave={(patch) =>
                  run(() => api.patchKC(draft.draft_id, selected.id, patch))
                }
                onDelete={() => {
                  setSelectedId(null);
                  run(() => api.deleteKC(draft.draft_id, selected.id));
                }}
              />
            ) : (
              <p className="muted">Select a node to review its attributes and source.</p>
            )}

            <ApproveBar
              validation={validation}
              approved={approved}
              approvedYaml={approvedYaml}
              busy={busy}
              onApprove={approve}
              onFocusIssue={focusIssue}
            />
          </div>
        </div>
      )}
    </div>
  );
}

type AddNodeProps = {
  disabled: boolean;
  existingIds: string[];
  onAdd: (kc: api.NewKC) => void;
};

function AddNodeForm({ disabled, existingIds, onAdd }: AddNodeProps) {
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [domain, setDomain] = useState<api.Domain>("safety");
  const clash = existingIds.includes(id.trim());
  const canAdd = id.trim() && name.trim() && !clash && !disabled;

  return (
    <div className="add-node">
      <input
        value={id}
        placeholder="KC id (e.g. SAF.001)"
        onChange={(e) => setId(e.target.value)}
      />
      <input value={name} placeholder="name" onChange={(e) => setName(e.target.value)} />
      <select value={domain} onChange={(e) => setDomain(e.target.value as api.Domain)}>
        {(["safety", "equipment", "process", "systems", "behavioural"] as const).map(
          (d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ),
        )}
      </select>
      <button
        className="primary"
        disabled={!canAdd}
        onClick={() => {
          onAdd({
            id: id.trim(),
            name: name.trim(),
            domain,
            description: "",
            regulation: null,
            known_misconceptions: [],
            superseded_by_kc_id: null,
            provenance: { doc_id: "", heading: "", excerpt: "" },
          });
          setId("");
          setName("");
        }}
      >
        Add node
      </button>
      {clash && <span className="warn">id already used</span>}
    </div>
  );
}
