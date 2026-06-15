const ICON = { high: '🟢', moderate: '🟡', low: '🔴' } as const;
const LABEL = { high: 'High', moderate: 'Moderate', low: 'Low' } as const;

export function ConfidenceChip({
  band,
  reasons,
}: {
  band: 'high' | 'moderate' | 'low';
  reasons: string[];
}) {
  const title = reasons.length ? reasons.join('\n') : `Confidence: ${LABEL[band]}`;
  return (
    <span className={`conf-chip ${band}`} title={title}>
      <span className="dot" />
      {ICON[band]} {LABEL[band]}
    </span>
  );
}
