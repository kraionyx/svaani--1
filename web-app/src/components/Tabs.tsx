const BASE_TABS: [string, string][] = [
  ['note', 'Consultation note'],
  ['risk', 'Risk markers'],
  ['extraction', 'Extraction'],
  ['transcript', 'Transcript'],
  ['grounding', 'Grounding'],
  ['speakers', 'Speakers'],
  ['ai-edit', 'AI Edit'],
  ['prescription', 'Prescription'],
];

export function Tabs({
  active,
  onTab,
  role,
}: {
  active: string;
  onTab: (t: string) => void;
  role?: string;
}) {
  const tabs: [string, string][] = role === 'admin' || role === 'auditor'
    ? [...BASE_TABS, ['admin', 'Admin']]
    : BASE_TABS;
  return (
    <div className="tabs">
      {tabs.map(([id, label]) => (
        <button key={id} className={active === id ? 'active' : ''} onClick={() => onTab(id)}>
          {label}
        </button>
      ))}
    </div>
  );
}
