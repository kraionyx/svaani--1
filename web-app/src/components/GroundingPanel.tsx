import { useStore } from '../store';

function List({ items, cls }: { items: string[]; cls?: string }) {
  if (!items?.length) return <p className="muted">none</p>;
  return <ul className={cls}>{items.map((x, i) => <li key={i}>{x}</li>)}</ul>;
}

export function GroundingPanel() {
  const g = useStore((s) => s.grounding);
  if (!g) return <div className="card muted">No grounding report.</div>;
  const nMis = (g.mismatched || []).length;
  return (
    <div className="card">
      <h2>Grounding &amp; fact verification — “only what was said”</h2>
      <p>Kept <b>{g.kept}</b> grounded items · dropped <b>{(g.dropped || []).length}</b> · flagged <b>{(g.flagged || []).length}</b>.</p>
      {nMis > 0 && <div className="disclaimer danger">⚠ {nMis} extracted value(s) were NOT found in the transcript they cite — likely inferred or normalized, not heard. Verify before signing.</div>}
      <p><b>Fact check — values not matching the transcript</b></p><List items={g.mismatched} cls="mismatched" />
      <p><b>Fact check — values confirmed in the transcript</b></p><List items={g.verified} cls="verified" />
      <p><b>Dropped (ungrounded / not in transcript)</b></p><List items={g.dropped} />
      <p><b>Flagged</b></p><List items={g.flagged} />
    </div>
  );
}
