// Validation surface + the Approve gate (plan §6). Approve is disabled while any blocker
// stands, but the real gate is server-side: the backend re-runs validation and refuses
// (422) regardless of this button. This banner just makes the blockers reviewable.

import type { ValidationIssue, ValidationResult } from "./api";

type Props = {
  validation: ValidationResult | null;
  approved: boolean;
  approvedYaml: string | null;
  busy: boolean;
  onApprove: () => void;
  onFocusIssue: (issue: ValidationIssue) => void;
};

export default function ApproveBar({
  validation,
  approved,
  approvedYaml,
  busy,
  onApprove,
  onFocusIssue,
}: Props) {
  const blockers = validation?.issues ?? [];
  const ok = validation?.ok ?? false;

  return (
    <div className="approve-bar">
      {blockers.length > 0 && (
        <div className="validation-banner validation-banner--error">
          <strong>{blockers.length} blocking issue(s)</strong>
          <ul>
            {blockers.map((issue, i) => (
              <li key={i}>
                <button className="link" onClick={() => onFocusIssue(issue)}>
                  <code>{issue.code}</code> {issue.message}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {validation && ok && !approved && (
        <div className="validation-banner validation-banner--ok">
          No blocking issues — ready to approve.
        </div>
      )}

      <button className="primary approve-btn" disabled={!ok || busy || approved} onClick={onApprove}>
        {approved ? "Approved ✓" : "Approve & materialize"}
      </button>

      {approvedYaml && (
        <details className="yaml-preview" open>
          <summary>Materialized graph.yaml (runtime loads this unmodified)</summary>
          <pre>{approvedYaml}</pre>
        </details>
      )}
    </div>
  );
}
