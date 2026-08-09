import type { KCInfo } from "./api/chat";

type Props = {
  kcs: KCInfo[];
};

/** Live, turn-by-turn view onto BKT posteriors (PRD §6.1/§7) — never computed
 * client-side, only rendered from what the backend already emits. */
export default function MasteryPanel({ kcs }: Props) {
  return (
    <aside className="mastery-panel">
      <h2>Mastery</h2>
      {kcs.length === 0 && <p className="mastery-panel__empty">No session yet.</p>}
      <ul className="mastery-panel__list">
        {kcs.map((kc) => {
          const pct = kc.mastery == null ? 0 : Math.round(kc.mastery * 100);
          return (
            <li key={kc.id} className={kc.gated ? "mastery-kc mastery-kc--gated" : "mastery-kc"}>
              <div className="mastery-kc__header">
                <span className="mastery-kc__name">{kc.name}</span>
                <span className="mastery-kc__pct">{kc.mastery == null ? "—" : `${pct}%`}</span>
              </div>
              <div className="mastery-kc__bar">
                <div className="mastery-kc__bar-fill" style={{ width: `${pct}%` }} />
              </div>
              {kc.gated && <span className="mastery-kc__gated-label">locked</span>}
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
