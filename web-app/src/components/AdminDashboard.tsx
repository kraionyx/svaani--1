import { useState, useEffect } from 'react';
import * as API from '../api';
import { useStore } from '../store';
import { toast } from '../toast';

const PIPELINE = [
  'issue_classification', 'prompt_evaluation', 'regression_test_generation',
  'prompt_optimization', 'offline_validation', 'human_approval', 'deployed',
];

type Tab = 'reviews' | 'improvements' | 'prompts' | 'flags' | 'analytics';

export function AdminDashboard() {
  const role = useStore((s) => s.role);
  const [tab, setTab] = useState<Tab>('reviews');
  const [reviews, setReviews] = useState<API.AdminReviewEntry[]>([]);
  const [improvements, setImprovements] = useState<API.ImprovementItem[]>([]);
  const [prompts, setPrompts] = useState<API.PromptVersion[]>([]);
  const [flags, setFlags] = useState<{ config: Record<string, any>; runtime: any[] } | null>(null);
  const [newName, setNewName] = useState('extract');
  const [newContent, setNewContent] = useState('');
  const [flagKey, setFlagKey] = useState('');
  const [flagOn, setFlagOn] = useState(true);
  const [errAnalytics, setErrAnalytics] = useState<Awaited<ReturnType<typeof API.getErrorAnalytics>> | null>(null);
  const [latAnalytics, setLatAnalytics] = useState<Awaited<ReturnType<typeof API.getLatencyAnalytics>> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (role !== 'admin' && role !== 'auditor') return;
    refresh();
  }, [role]);

  async function refresh() {
    const [rv, im, pr, fl, ea, la] = await Promise.allSettled([
      API.getAdminReviews(),
      API.getImprovements(),
      API.getPrompts(),
      API.getFeatureFlags(),
      API.getErrorAnalytics(),
      API.getLatencyAnalytics(),
    ]);
    if (rv.status === 'fulfilled') setReviews(rv.value);
    if (im.status === 'fulfilled') setImprovements(im.value);
    if (pr.status === 'fulfilled') setPrompts(pr.value);
    if (fl.status === 'fulfilled') setFlags(fl.value);
    if (ea.status === 'fulfilled') setErrAnalytics(ea.value);
    if (la.status === 'fulfilled') setLatAnalytics(la.value);
  }

  async function evalItem(id: string) {
    setBusy(id);
    try {
      const r = await API.runImprovementEval(id, { dataset: 'multispeaker@v1' });
      toast(`Eval ${r.passed ? 'PASS' : 'FAIL'} — attribution ${(r.attribution * 100).toFixed(0)}% (${r.n_cases} cases)`, !r.passed);
    } catch (e: any) { toast(e.message, true); }
    finally { setBusy(null); }
  }

  async function triage(id: string, status: 'approved' | 'rejected') {
    setBusy(id);
    try {
      await API.patchAdminReview(id, { status });
      toast(`Review ${status}.`);
      await refresh();
    } catch (e: any) { toast(e.message, true); }
    finally { setBusy(null); }
  }

  async function advance(id: string) {
    setBusy(id);
    try {
      const item = await API.advanceImprovement(id, {});
      setImprovements((is) => is.map((i) => i.id === id ? item : i));
      toast(`Advanced to: ${item.stage.replace(/_/g, ' ')}`);
    } catch (e: any) { toast(e.message, true); }
    finally { setBusy(null); }
  }

  async function addPrompt() {
    if (!newContent.trim()) return;
    setBusy('new-prompt');
    try {
      await API.createPrompt({ name: newName, content: newContent, activate: false });
      setNewContent('');
      toast('Prompt version created (inactive).');
      const updated = await API.getPrompts();
      setPrompts(updated);
    } catch (e: any) { toast(e.message, true); }
    finally { setBusy(null); }
  }

  async function doActivate(id: string) {
    setBusy(id);
    try {
      await API.activatePrompt(id);
      toast('Prompt activated.');
      const updated = await API.getPrompts();
      setPrompts(updated);
    } catch (e: any) { toast(e.message, true); }
    finally { setBusy(null); }
  }

  async function setFlag() {
    if (!flagKey.trim()) return;
    setBusy('flag');
    try {
      await API.setFeatureFlag({ key: flagKey.trim(), enabled: flagOn });
      toast(`Flag "${flagKey.trim()}" set to ${flagOn}.`);
      setFlagKey('');
      const updated = await API.getFeatureFlags();
      setFlags(updated);
    } catch (e: any) { toast(e.message, true); }
    finally { setBusy(null); }
  }

  if (role !== 'admin' && role !== 'auditor') {
    return <div className="card muted empty">Admin or auditor role required.</div>;
  }

  const TABS: [Tab, string][] = [
    ['reviews', `Reviews${reviews.length ? ` (${reviews.length})` : ''}`],
    ['improvements', 'Improvements'],
    ['prompts', 'Prompts'],
    ['flags', 'Feature flags'],
    ['analytics', 'Analytics'],
  ];

  return (
    <div className="card">
      <div className="note-head">
        <h2 style={{ margin: 0 }}>Admin dashboard</h2>
        <button className="btn ghost sm" onClick={refresh}>Refresh</button>
      </div>

      <div className="tabs" style={{ margin: '8px 0 14px' }}>
        {TABS.map(([id, label]) => (
          <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{label}</button>
        ))}
      </div>

      {tab === 'reviews' && (
        <div>
          {reviews.length === 0 ? (
            <div className="muted kv">No reviews pending.</div>
          ) : reviews.map((entry) => (
            <div key={entry.admin_review.id} className="admin-row">
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>
                  {entry.review.rating === 'needs_improvement' ? '👎' : '👍'}{' '}
                  {entry.review.rating?.replace(/_/g, ' ')}
                </div>
                <div className="adm-meta">
                  {entry.review.session_id?.slice(0, 20)} ·{' '}
                  {(entry.review.error_categories || []).join(', ') || 'no categories'}
                  {entry.review.comment ? ` · "${entry.review.comment}"` : ''}
                </div>
              </div>
              <span className={`px-status ${entry.admin_review.status}`}>{entry.admin_review.status}</span>
              {entry.admin_review.status === 'pending' && (
                <div className="row" style={{ gap: 6, margin: 0 }}>
                  <button
                    className="btn sm"
                    style={{ background: 'var(--ok)' }}
                    disabled={!!busy}
                    onClick={() => triage(entry.admin_review.id, 'approved')}
                  >
                    {busy === entry.admin_review.id ? '…' : 'Approve'}
                  </button>
                  <button
                    className="btn ghost sm"
                    disabled={!!busy}
                    onClick={() => triage(entry.admin_review.id, 'rejected')}
                  >
                    Reject
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {tab === 'improvements' && (
        <div>
          {improvements.length === 0 ? (
            <div className="muted kv">No improvement items.</div>
          ) : improvements.map((item) => (
            <div key={item.id} className="admin-row">
              <span className="stage-pill">{item.stage.replace(/_/g, ' ')}</span>
              <span className="adm-meta" style={{ flex: 1, marginLeft: 8 }}>
                {item.id.slice(0, 18)}
              </span>
              {role === 'admin' && (
                <button className="btn ghost sm" disabled={!!busy} onClick={() => evalItem(item.id)}>
                  {busy === item.id ? '…' : 'Run eval'}
                </button>
              )}
              {item.stage !== 'deployed' && (
                <button className="btn ghost sm" disabled={!!busy} onClick={() => advance(item.id)}>
                  {busy === item.id ? '…' : 'Advance →'}
                </button>
              )}
            </div>
          ))}
          <div className="disclaimer" style={{ marginTop: 12, fontSize: 11 }}>
            Pipeline: {PIPELINE.map((s, i) => (
              <span key={s}>{i > 0 && ' → '}<b>{s.replace(/_/g, ' ')}</b></span>
            ))}
          </div>
        </div>
      )}

      {tab === 'prompts' && (
        <div>
          {prompts.map((p) => (
            <div key={p.id} className="prompt-item">
              <div className="ph">
                <span className="stage-pill">{p.name} v{p.version}</span>
                {p.active && <span className="badge" style={{ background: 'var(--ok)', color: '#fff' }}>Active</span>}
                <span className="adm-meta">{p.content_hash.slice(0, 10)}</span>
                {!p.active && role === 'admin' && (
                  <button className="btn ghost sm" style={{ marginLeft: 'auto' }} disabled={!!busy} onClick={() => doActivate(p.id)}>
                    {busy === p.id ? '…' : 'Activate'}
                  </button>
                )}
              </div>
              <pre>{p.content.slice(0, 220)}{p.content.length > 220 ? '…' : ''}</pre>
            </div>
          ))}

          {role === 'admin' && (
            <div style={{ borderTop: '1px solid var(--border)', marginTop: 14, paddingTop: 14 }}>
              <h3 style={{ fontSize: 13, margin: '0 0 10px' }}>New prompt version</h3>
              <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
                <div style={{ flex: '0 0 120px' }}>
                  <label className="lbl">Name</label>
                  <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="extract" />
                </div>
                <div style={{ flex: 1, minWidth: 220 }}>
                  <label className="lbl">Content</label>
                  <textarea value={newContent} onChange={(e) => setNewContent(e.target.value)} placeholder="New prompt content…" rows={3} />
                </div>
              </div>
              <button className="btn sm" style={{ marginTop: 8 }} disabled={!!busy || !newContent.trim()} onClick={addPrompt}>
                {busy === 'new-prompt' ? 'Creating…' : 'Create (inactive)'}
              </button>
            </div>
          )}
        </div>
      )}

      {tab === 'analytics' && (
        <div>
          <h3 style={{ fontSize: 13, margin: '0 0 8px' }}>Doctor feedback ({errAnalytics?.total_reviews ?? 0} reviews)</h3>
          {errAnalytics && Object.keys(errAnalytics.by_error_category).length > 0 ? (
            <table className="edit-tbl" style={{ marginBottom: 16 }}>
              <thead><tr><th>Error category</th><th>Count</th></tr></thead>
              <tbody>
                {Object.entries(errAnalytics.by_error_category).map(([k, n]) => (
                  <tr key={k}><td>{k.replace(/_/g, ' ')}</td><td>{n}</td></tr>
                ))}
              </tbody>
            </table>
          ) : <div className="muted kv" style={{ marginBottom: 16 }}>No error categories recorded yet.</div>}

          <h3 style={{ fontSize: 13, margin: '0 0 8px' }}>Stage latency (p50 / p95)</h3>
          {latAnalytics && Object.keys(latAnalytics.stages).length > 0 ? (
            <table className="edit-tbl">
              <thead><tr><th>Stage</th><th>n</th><th>p50 ms</th><th>p95 ms</th></tr></thead>
              <tbody>
                {Object.entries(latAnalytics.stages).map(([stage, v]) => (
                  <tr key={stage}><td>{stage}</td><td>{v.n}</td><td>{v.p50_ms}</td><td>{v.p95_ms}</td></tr>
                ))}
              </tbody>
            </table>
          ) : <div className="muted kv">No latency telemetry yet — run a consultation.</div>}
        </div>
      )}

      {tab === 'flags' && flags && (
        <div>
          <h3 style={{ fontSize: 13, margin: '0 0 8px' }}>Config flags (read-only)</h3>
          <table className="edit-tbl" style={{ marginBottom: 14 }}>
            <tbody>
              {Object.entries(flags.config).map(([k, v]) => (
                <tr key={k}>
                  <td style={{ fontWeight: 600 }}>{k}</td>
                  <td style={{ color: v === true ? 'var(--ok)' : v === false ? 'var(--muted)' : 'var(--ink)' }}>
                    {String(v)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3 style={{ fontSize: 13, margin: '0 0 8px' }}>Runtime flags</h3>
          {flags.runtime.length === 0 ? (
            <div className="muted kv">No runtime flags set.</div>
          ) : flags.runtime.map((f: any) => (
            <div key={f.key} className="admin-row">
              <span style={{ fontWeight: 600 }}>{f.key}</span>
              <span className={`px-status ${f.enabled ? 'approved' : 'draft'}`}>{f.enabled ? 'on' : 'off'}</span>
            </div>
          ))}

          {role === 'admin' && (
            <div style={{ borderTop: '1px solid var(--border)', marginTop: 12, paddingTop: 12 }}>
              <h3 style={{ fontSize: 13, margin: '0 0 8px' }}>Set flag</h3>
              <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                <div style={{ flex: 1, minWidth: 140 }}>
                  <label className="lbl">Flag key</label>
                  <input value={flagKey} onChange={(e) => setFlagKey(e.target.value)} placeholder="feature.name" />
                </div>
                <div>
                  <label className="lbl">Enabled</label>
                  <select value={flagOn ? 'true' : 'false'} onChange={(e) => setFlagOn(e.target.value === 'true')}>
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                </div>
                <button className="btn sm" disabled={!!busy || !flagKey.trim()} onClick={setFlag}>
                  {busy === 'flag' ? '…' : 'Set flag'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
