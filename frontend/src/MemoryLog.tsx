import { deleteFact, type StoredFact } from "./api/chat";

type Props = {
  facts: StoredFact[];
  onDeleted: (factId: number) => void;
};

/** Streams extracted `PersonalFact`s as they happen (PRD §7): fact capture visible
 * in real time, plus the employee's right to see/delete what Sofía remembers. */
export default function MemoryLog({ facts, onDeleted }: Props) {
  async function handleDelete(factId: number) {
    await deleteFact(factId);
    onDeleted(factId);
  }

  return (
    <aside className="memory-log">
      <h2>Memory</h2>
      {facts.length === 0 && <p className="memory-log__empty">Nothing remembered yet.</p>}
      <ul className="memory-log__list">
        {facts.map((entry) => (
          <li key={entry.id} className="memory-log__entry">
            <span className="memory-log__time">
              {new Date(entry.created_at).toLocaleTimeString()}
            </span>
            <span className="memory-log__fact">
              {entry.fact.fact_type}: {entry.fact.value}
            </span>
            <button
              type="button"
              className="memory-log__delete"
              onClick={() => handleDelete(entry.id)}
              aria-label={`Forget ${entry.fact.fact_type}`}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
