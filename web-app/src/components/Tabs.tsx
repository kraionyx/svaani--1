const TABS = [
  ['note', 'Consultation note'], ['risk', 'Risk markers'], ['extraction', 'Extraction'],
  ['transcript', 'Transcript'], ['grounding', 'Grounding'],
];

export function Tabs({ active, onTab }: { active: string; onTab: (t: string) => void }) {
  return (
    <div className="tabs">
      {TABS.map(([id, label]) => (
        <button key={id} className={active === id ? 'active' : ''} onClick={() => onTab(id)}>{label}</button>
      ))}
    </div>
  );
}
