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
    <div className="sticky top-0 z-20 bg-[#eef1f7]/90 backdrop-blur-md border-b border-slate-200/50 flex flex-col md:flex-row md:items-center justify-between px-4 md:px-6 -mx-4 md:-mx-6 pt-4 pb-0 mb-4 md:mb-6 w-[calc(100%+2rem)] md:w-[calc(100%+3rem)] shadow-sm gap-3 md:gap-0">
      <div className="flex gap-5 md:gap-6 overflow-x-auto hidden-scrollbar w-full">
        {tabs.map(([id, label]) => (
          <button 
            key={id} 
            className={`pb-2 md:pb-3 text-[13px] md:text-sm font-medium transition-all border-b-2 whitespace-nowrap shrink-0 ${active === id ? 'border-sky-500 text-sky-700' : 'border-transparent text-slate-500 hover:text-slate-800'}`} 
            onClick={() => onTab(id)}
          >
            {label}
          </button>
        ))}
      </div>
      {rightAction && (
        <div className="pb-3 md:pb-2 self-start md:self-auto shrink-0 hidden md:block">
          {rightAction}
        </div>
      )}
    </div>
  );
}
