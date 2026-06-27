const BASE_TABS: [string, string][] = [
  ['note', 'Consultation note'],
  ['risk', 'Risk markers'],
  ['extraction', 'Extraction'],
  ['transcript', 'Transcript'],
  ['grounding', 'Grounding'],
  ['speakers', 'Speakers'],
  ['prescription', 'Prescription'],
];

export function Tabs({
  active,
  onTab,
  role,
  rightAction,
}: {
  active: string;
  onTab: (t: string) => void;
  role?: string;
  rightAction?: React.ReactNode;
}) {
  const tabs: [string, string][] = role === 'admin' || role === 'auditor'
    ? [...BASE_TABS, ['admin', 'Admin']]
    : BASE_TABS;
  return (
    <div className="sticky top-0 z-20 bg-[#eef1f7]/90 backdrop-blur-md border-b border-slate-200/50 flex items-center justify-between px-6 -mx-6 pt-4 pb-0 mb-6 w-[calc(100%+3rem)] shadow-sm">
      <div className="flex gap-6">
        {tabs.map(([id, label]) => (
          <button 
            key={id} 
            className={`pb-3 text-sm font-medium transition-all border-b-2 ${active === id ? 'border-sky-500 text-sky-700' : 'border-transparent text-slate-500 hover:text-slate-800'}`} 
            onClick={() => onTab(id)}
          >
            {label}
          </button>
        ))}
      </div>
      {rightAction && (
        <div className="pb-2">
          {rightAction}
        </div>
      )}
    </div>
  );
}
