// Typed client for the studio API (backend app/api/studio.py). Mirrors the Pydantic
// models by hand — a handful of types, no codegen for a slice this size.

export type Domain = "safety" | "equipment" | "process" | "systems" | "behavioural";
export type Origin = "extracted" | "edited" | "manual";
export type DraftStatus = "extracting" | "draft" | "approved" | "failed";

export type Provenance = {
  doc_id: string;
  heading: string;
  excerpt: string;
};

export type ProposedKC = {
  id: string;
  name: string;
  domain: Domain;
  description: string;
  regulation: string | null;
  known_misconceptions: string[];
  superseded_by_kc_id: string | null;
  provenance: Provenance;
  origin: Origin;
};

export type ProposedEdge = {
  source_kc_id: string;
  target_kc_id: string;
  rationale: string;
  provenance: Provenance | null;
  origin: Origin;
};

export type GraphDraft = {
  draft_id: string;
  role: string;
  status: DraftStatus;
  source_docs: string[];
  kcs: ProposedKC[];
  edges: ProposedEdge[];
};

export type IssueCode =
  | "duplicate_kc_id"
  | "missing_provenance"
  | "dangling_edge"
  | "self_loop"
  | "cycle";

export type ValidationIssue = {
  code: IssueCode;
  message: string;
  kc_id: string | null;
  edge: [string, string] | null;
};

export type ValidationResult = {
  ok: boolean;
  issues: ValidationIssue[];
};

export type ApproveResponse = {
  draft_id: string;
  status: DraftStatus;
  path: string;
  yaml: string;
};

const BASE = "/api/studio";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text();
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`studio API ${status}: ${detail}`);
  }
}

export async function createDraft(
  role: string,
  seedFromGraph: boolean,
): Promise<GraphDraft> {
  const form = new FormData();
  form.set("role", role);
  form.set("seed_from_graph", String(seedFromGraph));
  return json(await fetch(`${BASE}/drafts`, { method: "POST", body: form }));
}

export async function listDrafts(): Promise<GraphDraft[]> {
  return json(await fetch(`${BASE}/drafts`));
}

export async function getDraft(id: string): Promise<GraphDraft> {
  return json(await fetch(`${BASE}/drafts/${id}`));
}

export async function getValidation(id: string): Promise<ValidationResult> {
  return json(await fetch(`${BASE}/drafts/${id}/validation`));
}

export type NewKC = Omit<ProposedKC, "origin">;

export async function addKC(id: string, body: NewKC): Promise<GraphDraft> {
  return json(
    await fetch(`${BASE}/drafts/${id}/kcs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export type KCPatch = Partial<Omit<ProposedKC, "id" | "origin">>;

export async function patchKC(
  id: string,
  kcId: string,
  patch: KCPatch,
): Promise<GraphDraft> {
  return json(
    await fetch(`${BASE}/drafts/${id}/kcs/${kcId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  );
}

export async function deleteKC(id: string, kcId: string): Promise<GraphDraft> {
  return json(await fetch(`${BASE}/drafts/${id}/kcs/${kcId}`, { method: "DELETE" }));
}

export async function addEdge(
  id: string,
  source: string,
  target: string,
  rationale: string,
): Promise<GraphDraft> {
  return json(
    await fetch(`${BASE}/drafts/${id}/edges`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_kc_id: source,
        target_kc_id: target,
        rationale,
      }),
    }),
  );
}

export async function deleteEdge(
  id: string,
  source: string,
  target: string,
): Promise<GraphDraft> {
  const params = new URLSearchParams({ source_kc_id: source, target_kc_id: target });
  return json(
    await fetch(`${BASE}/drafts/${id}/edges?${params}`, { method: "DELETE" }),
  );
}

export async function approveDraft(id: string): Promise<ApproveResponse> {
  return json(await fetch(`${BASE}/drafts/${id}/approve`, { method: "POST" }));
}

export async function previewYaml(id: string): Promise<string> {
  const data = await json<{ yaml: string }>(
    await fetch(`${BASE}/drafts/${id}/yaml`),
  );
  return data.yaml;
}

// --- SOP extraction -------------------------------------------------------

export type SopDoc = { doc_id: string; filename: string; chars: number };

export type ExtractionEvent = {
  type:
    | "doc_started"
    | "doc_done"
    | "reconciled"
    | "edges_started"
    | "edges_done"
    | "validated"
    | "done"
    | "failed";
  doc_id: string | null;
  detail: string | null;
  kc_count: number | null;
  edge_count: number | null;
};

export async function listSops(): Promise<SopDoc[]> {
  return json(await fetch(`${BASE}/sops`));
}

/** Create a draft by extraction over selected committed SOPs plus any uploaded files. */
export async function createDraftFromSops(
  role: string,
  sopIds: string[],
  files: File[],
): Promise<GraphDraft> {
  const form = new FormData();
  form.set("role", role);
  form.set("sop_ids", sopIds.join(","));
  for (const file of files) form.append("files", file);
  return json(await fetch(`${BASE}/drafts/extract`, { method: "POST", body: form }));
}

export type ExtractionHandlers = {
  onProgress: (event: ExtractionEvent) => void;
  onEnd: () => void;
  onError?: () => void;
};

/** Open the SSE progress stream for a running extraction. Caller closes the EventSource. */
export function openExtractionStream(
  draftId: string,
  handlers: ExtractionHandlers,
): EventSource {
  const es = new EventSource(`${BASE}/drafts/${draftId}/events`);
  es.addEventListener("progress", (e) => {
    handlers.onProgress(JSON.parse((e as MessageEvent).data) as ExtractionEvent);
  });
  es.addEventListener("end", () => handlers.onEnd());
  es.onerror = () => handlers.onError?.();
  return es;
}
