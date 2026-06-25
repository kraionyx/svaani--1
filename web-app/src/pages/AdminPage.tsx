// AdminPage.tsx
import { useState, useEffect, useCallback, useRef } from 'react';


const TOKEN_KEY = 'svaani-admin-token';
const BASE = '/admin1/api';

function adminHeaders(): HeadersInit {
  return {
    'Content-Type': 'application/json',
    'X-Admin-Token': localStorage.getItem(TOKEN_KEY) || '',
  };
}

async function api<T = any>(path: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, { headers: adminHeaders(), ...opts });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(text || r.statusText);
  }
  return r.json();
}

// ── Small inline chart helpers ────────────────────────────────────────────
function Bar({ value, max, color = '#a3e635' }: { value: number; max: number; color?: string }) {
  const pct = max ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div style={{ height: 6, background: '#1e293b', borderRadius: 3, overflow: 'hidden', width: '100%' }}>
      <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 3, transition: 'width 0.3s' }} />
    </div>
  );
}

function StackedBarChart({ data, labels }: { data: Record<string, number>; labels: Record<string, string> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(...entries.map(e => e[1]), 1);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {entries.map(([key, count]) => (
        <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 100, fontSize: 11, color: '#94a3b8', textAlign: 'right' }}>{labels?.[key] || key}</span>
          <div style={{ flex: 1 }}>
            <Bar value={count} max={max} color={key.includes('helpful') ? '#a3e635' : '#f87171'} />
          </div>
          <span style={{ width: 30, fontSize: 11, color: '#64748b', textAlign: 'right' }}>{count}</span>
        </div>
      ))}
    </div>
  );
}

// ── Reusable UI components ─────────────────────────────────────────────────
function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div style={css.statCard}>
      <div style={{ fontSize: 22, fontWeight: 700, color: '#a3e635' }}>{value}</div>
      <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>{label}</div>
      {sub && <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>{sub}</div>}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 style={css.sectionTitle}>{children}</h3>;
}

function Table({ cols, rows }: { cols: string[]; rows: (string | number | null | undefined)[][] }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr>{cols.map((c) => <th key={c} style={css.th}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={cols.length} style={{ padding: 16, textAlign: 'center', color: '#64748b' }}>No data</td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)' }}>
                {row.map((cell, j) => (
                  <td key={j} style={css.td}>{cell ?? '—'}</td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function Pager({ page, total, limit, onPage }: { page: number; total: number; limit: number; onPage: (p: number) => void }) {
  const pages = Math.ceil(total / limit) || 1;
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12, fontSize: 12, color: '#94a3b8' }}>
      <button style={css.pgBtn} disabled={page <= 1} onClick={() => onPage(page - 1)}>‹ Prev</button>
      <span>Page {page} of {pages} ({total} total)</span>
      <button style={css.pgBtn} disabled={page >= pages} onClick={() => onPage(page + 1)}>Next ›</button>
    </div>
  );
}

function FilterInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{ fontSize: 11, color: '#64748b' }}>{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ ...css.input, width: 130, padding: '4px 8px', fontSize: 12 }}
        placeholder={label}
      />
    </label>
  );
}

// ── Tab: Overview ──────────────────────────────────────────────────────────
function TabOverview() {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    api('/overview').then(setData).catch((e) => setErr(e.message));
  }, []);

  if (err) return <div style={css.errBox}>{err}</div>;
  if (!data) return <div style={css.spinner}>Loading…</div>;

  const kpis = data.kpis || {};
  return (
    <div>
      <SectionTitle>Key Metrics (24 h)</SectionTitle>
      <div style={css.statGrid}>
        <StatCard label="Total Requests" value={kpis.total_requests_24h ?? 0} />
        <StatCard label="Error Rate" value={kpis.error_rate_pct != null ? kpis.error_rate_pct.toFixed(1) + '%' : '—'} />
        <StatCard label="Avg Latency" value={kpis.avg_latency_ms != null ? kpis.avg_latency_ms + ' ms' : '—'} />
        <StatCard label="Active Doctors" value={kpis.active_doctors_24h ?? 0} />
        <StatCard label="AI Calls (24h)" value={kpis.ai_calls_24h ?? 0} />
        <StatCard label="AI Cost (24h)" value={kpis.ai_cost_24h_usd != null ? '$' + Number(kpis.ai_cost_24h_usd).toFixed(4) : '—'} />
        <StatCard label="Total Sessions" value={kpis.total_sessions ?? 0} />
        <StatCard label="Total Reports" value={kpis.total_reports ?? 0} />
      </div>
      {/* additional data: top doctors, recent errors already present */}
    </div>
  );
}

// ── Tab: Doctors ───────────────────────────────────────────────────────────
function TabDoctors() {
  const [data, setData] = useState<any>(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [err, setErr] = useState('');

  const load = useCallback(() => {
    api(`/doctors?page=${page}&limit=20&search=${encodeURIComponent(search)}`)
      .then(setData)
      .catch((e) => setErr(e.message));
  }, [page, search]);

  useEffect(() => { load(); }, [load]);

  if (err) return <div style={css.errBox}>{err}</div>;

  const rows = (data?.doctors || []).map((d: any) => [
    d.user_id, d.full_name || '—', d.email || '—', d.organization || '—',
    d.total_sessions, d.total_requests, d.total_ai_calls, d.total_reports,
    d.total_session_seconds != null ? Math.round(d.total_session_seconds / 60) + ' min' : '—',
    fmtDate(d.last_active),
  ]);

  return (
    <div>
      <div style={{ display: 'flex', gap: 10, marginBottom: 14, alignItems: 'flex-end' }}>
        <FilterInput label="Search" value={search} onChange={(v) => { setSearch(v); setPage(1); }} />
        <button style={css.btn} onClick={load}>Refresh</button>
      </div>
      {!data ? <div style={css.spinner}>Loading…</div> : (
        <>
          <Table
            cols={['User ID', 'Name', 'Email', 'Org', 'Sessions', 'Requests', 'AI Calls', 'Reports', 'Time', 'Last Active']}
            rows={rows}
          />
          <Pager page={page} total={data.total || 0} limit={20} onPage={setPage} />
        </>
      )}
    </div>
  );
}

// ── Tab: System Health ─────────────────────────────────────────────────────
function TabHealth() {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState('');
  const load = () => api('/health').then(setData).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  if (err) return <div style={css.errBox}>{err}</div>;
  if (!data) return <div style={css.spinner}>Loading…</div>;

  const latency = data.latency || {};
  const endpoints = data.slowest_endpoints || [];
  const errors = data.error_summary || {};

  return (
    <div>
      <SectionTitle>API Latency (1 h)</SectionTitle>
      <div style={css.statGrid}>
        <StatCard label="p50" value={latency.p50_ms != null ? latency.p50_ms + ' ms' : '—'} />
        <StatCard label="p95" value={latency.p95_ms != null ? latency.p95_ms + ' ms' : '—'} />
        <StatCard label="p99" value={latency.p99_ms != null ? latency.p99_ms + ' ms' : '—'} />
        <StatCard label="Max" value={latency.max_ms != null ? latency.max_ms + ' ms' : '—'} />
        <StatCard label="Avg" value={latency.avg_ms != null ? latency.avg_ms + ' ms' : '—'} />
        <StatCard label="Total Requests" value={latency.count ?? '—'} />
      </div>
      {/* error summary chart */}
      {Object.keys(errors).length > 0 && (
        <>
          <SectionTitle>Errors by Type (24 h)</SectionTitle>
          <StackedBarChart data={errors} labels={{}} />
        </>
      )}
      {endpoints.length > 0 && (
        <>
          <SectionTitle>Slowest Endpoints</SectionTitle>
          <Table
            cols={['Endpoint', 'Avg ms', 'Max ms', 'Count']}
            rows={endpoints.map((e: any) => [e.endpoint, e.avg_ms, e.max_ms, e.count])}
          />
        </>
      )}
    </div>
  );
}

// ── Tab: Logs Explorer ─────────────────────────────────────────────────────
function TabLogs() {
  const [data, setData] = useState<any>(null);
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({ user_id: '', endpoint: '', status: '', from_dt: '', to_dt: '' });
  const [err, setErr] = useState('');

  const load = useCallback(() => {
    const q = new URLSearchParams({ page: String(page), limit: '50', ...filters });
    api(`/logs?${q}`).then(setData).catch((e) => setErr(e.message));
  }, [page, filters]);

  useEffect(() => { load(); }, [load]);

  const rows = (data?.logs || []).map((l: any) => [
    fmtDate(l.created_at), l.method, l.endpoint, l.status_code,
    l.duration_ms != null ? l.duration_ms + ' ms' : '—', l.user_id || '—',
  ]);

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14, alignItems: 'flex-end' }}>
        {Object.entries({
          'User ID': 'user_id',
          'Endpoint': 'endpoint',
          'Status': 'status',
          'From (ISO)': 'from_dt',
          'To (ISO)': 'to_dt',
        }).map(([label, key]) => (
          <FilterInput
            key={key}
            label={label}
            value={filters[key as keyof typeof filters]}
            onChange={(v) => setFilters((prev) => ({ ...prev, [key]: v }))}
          />
        ))}
        <button style={css.btn} onClick={load}>Apply</button>
      </div>
      {err && <div style={css.errBox}>{err}</div>}
      {!data ? <div style={css.spinner}>Loading…</div> : (
        <>
          <Table cols={['Time', 'Method', 'Endpoint', 'Status', 'Latency', 'User']} rows={rows} />
          <Pager page={page} total={data.total || 0} limit={50} onPage={setPage} />
        </>
      )}
    </div>
  );
}

// ── Tab: Errors ────────────────────────────────────────────────────────────
function relTime(iso?: string): string {
  if (!iso) return '—';
  const t = new Date(iso.replace(' ', 'T')).getTime();
  if (isNaN(t)) return iso;
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// Grouped (default) view: each DISTINCT error signature once, with how many times it fired
// and when it first/last occurred — so repeated failures don't flood the list. Toggle to the
// raw Timeline for chronological, per-occurrence inspection.
function TabErrors() {
  const [view, setView] = useState<'grouped' | 'timeline'>('grouped');
  const [data, setData] = useState<any>(null);
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({ severity: '', source: '', from_dt: '', to_dt: '' });
  const [expanded, setExpanded] = useState<string | null>(null);
  const [err, setErr] = useState('');

  const load = useCallback(() => {
    setErr('');
    if (view === 'grouped') {
      const q = new URLSearchParams({ limit: '100', ...filters });
      api(`/errors/grouped?${q}`).then(setData).catch((e) => setErr(e.message));
    } else {
      const q = new URLSearchParams({ page: String(page), limit: '50', ...filters });
      api(`/errors?${q}`).then(setData).catch((e) => setErr(e.message));
    }
  }, [view, page, filters]);

  useEffect(() => { load(); }, [load]);

  const groups = data?.groups || [];
  const errors = data?.errors || [];

  const Toggle = (
    <div style={{ display: 'flex', gap: 0, border: '1px solid #1e293b', borderRadius: 6, overflow: 'hidden' }}>
      {(['grouped', 'timeline'] as const).map((v) => (
        <button
          key={v}
          onClick={() => { setView(v); setPage(1); setData(null); }}
          style={{
            ...css.smBtn, borderRadius: 0, border: 'none',
            background: view === v ? '#a3e635' : 'transparent',
            color: view === v ? '#0a0e16' : '#94a3b8', fontWeight: view === v ? 700 : 500,
            textTransform: 'capitalize',
          }}
        >{v}</button>
      ))}
    </div>
  );

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14, alignItems: 'flex-end' }}>
        {Toggle}
        {Object.entries({ Severity: 'severity', Source: 'source', 'From (ISO)': 'from_dt', 'To (ISO)': 'to_dt' }).map(([label, key]) => (
          <FilterInput
            key={key}
            label={label}
            value={filters[key as keyof typeof filters]}
            onChange={(v) => setFilters((prev) => ({ ...prev, [key]: v }))}
          />
        ))}
        <button style={css.btn} onClick={load}>Apply</button>
      </div>
      {err && <div style={css.errBox}>{err}</div>}
      {!data ? <div style={css.spinner}>Loading…</div> : view === 'grouped' ? (
        <div>
          {groups.length === 0 && <div style={{ color: '#64748b', fontSize: 13 }}>No errors found.</div>}
          {groups.map((g: any, i: number) => {
            const id = `g${i}`;
            return (
              <div key={id} style={{ ...css.errRow, borderLeft: `3px solid ${severityColor(g.severity)}` }}>
                <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                  <span style={{
                    minWidth: 38, textAlign: 'center', fontSize: 12, fontWeight: 800,
                    color: '#0a0e16', background: severityColor(g.severity), borderRadius: 10, padding: '1px 8px',
                  }}>{g.count}×</span>
                  <span style={{ fontSize: 11, color: severityColor(g.severity), fontWeight: 600, minWidth: 56 }}>{g.severity}</span>
                  <span style={{ fontSize: 11, color: '#94a3b8', minWidth: 64 }}>{g.source}</span>
                  <span style={{ fontSize: 12, color: '#e2e8f0', fontWeight: 600 }}>{g.error_type}</span>
                  <span style={{ fontSize: 12, color: '#cbd5e1', flex: 1, minWidth: 120 }}>{(g.message || '').slice(0, 90)}</span>
                  <span style={{ fontSize: 11, color: '#64748b', whiteSpace: 'nowrap' }} title={`first ${g.first_seen}\nlast ${g.last_seen}`}>
                    last {relTime(g.last_seen)}
                  </span>
                </div>
                <div style={css.errStackSection}>
                  <div style={{ display: 'flex', gap: '8px', marginBottom: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                    <button style={css.smBtn} onClick={() => setExpanded(expanded === id ? null : id)}>
                      {expanded === id ? 'Hide' : 'Details'}
                    </button>
                    {g.sample_endpoint && <span style={{ fontSize: 11, color: '#64748b' }}>at <code style={{ color: '#94a3b8' }}>{g.sample_endpoint}</code></span>}
                    <span style={{ fontSize: 11, color: '#64748b' }}>first seen {relTime(g.first_seen)}</span>
                    {g.sample_ai && (
                      <span style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6', padding: '2px 8px', borderRadius: 12, fontSize: 11, fontWeight: 500 }}>🤖 Agent Analysis</span>
                    )}
                  </div>
                  {expanded === id && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 8 }}>
                      {g.sample_ai && (
                        <div style={{ background: '#1e293b', padding: 12, borderRadius: 4 }}>
                          <div style={{ fontSize: '0.85rem', color: '#94a3b8', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Agent Triaged Analysis (latest sample)</div>
                          <pre style={{ margin: 0, fontSize: '0.85rem', color: '#f1f5f9', whiteSpace: 'pre-wrap', fontFamily: 'system-ui, sans-serif' }}>{g.sample_ai}</pre>
                        </div>
                      )}
                      {g.sample_stack && (
                        <div>
                          <div style={{ fontSize: '0.85rem', color: '#94a3b8', marginBottom: 4 }}>Stack Trace (latest sample)</div>
                          <pre style={css.errStack}>{g.sample_stack}</pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
          <div style={{ marginTop: 12, fontSize: 12, color: '#64748b' }}>{groups.length} distinct error{groups.length === 1 ? '' : 's'} (ranked by frequency).</div>
        </div>
      ) : (
        <div>
          {errors.length === 0 && <div style={{ color: '#64748b', fontSize: 13 }}>No errors found.</div>}
          {errors.map((e: any) => (
            <div key={e.id} style={{ ...css.errRow, borderLeft: `3px solid ${severityColor(e.severity)}` }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: '#64748b', minWidth: 130 }}>{fmtDate(e.created_at)}</span>
                <span style={{ fontSize: 11, color: severityColor(e.severity), fontWeight: 600, minWidth: 60 }}>{e.severity}</span>
                <span style={{ fontSize: 11, color: '#94a3b8', minWidth: 70 }}>{e.source}</span>
                <span style={{ fontSize: 12, color: '#e2e8f0', fontWeight: 600 }}>{e.error_type}</span>
                <span style={{ fontSize: 12, color: '#cbd5e1', flex: 1 }}>{(e.error_message || '').slice(0, 80)}</span>
              </div>
              <div style={css.errStackSection}>
                <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
                  <button style={css.smBtn} onClick={() => setExpanded(expanded === e.id ? null : e.id)}>
                    {expanded === e.id ? 'Hide' : 'Details'}
                  </button>
                  {e.ai_analysis && (
                    <span style={{ backgroundColor: 'rgba(59, 130, 246, 0.1)', color: '#3b82f6', padding: '2px 8px', borderRadius: '12px', fontSize: '0.85rem', fontWeight: 500, display: 'flex', alignItems: 'center', gap: '4px' }}>🤖 Agent Analysis Available</span>
                  )}
                </div>
                {expanded === e.id && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginTop: '8px' }}>
                    {e.ai_analysis && (
                      <div style={{ backgroundColor: '#1e293b', padding: '12px', borderRadius: '4px' }}>
                        <div style={{ fontSize: '0.85rem', color: '#94a3b8', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Agent Triaged Analysis</div>
                        <pre style={{ margin: 0, fontSize: '0.85rem', color: '#f1f5f9', whiteSpace: 'pre-wrap', fontFamily: 'system-ui, sans-serif' }}>
                          {e.ai_analysis}
                        </pre>
                      </div>
                    )}
                    {e.stack_trace && (
                      <div>
                        <div style={{ fontSize: '0.85rem', color: '#94a3b8', marginBottom: '4px' }}>Stack Trace</div>
                        <pre style={css.errStack}>{e.stack_trace}</pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
          <Pager page={page} total={data.total || 0} limit={50} onPage={setPage} />
        </div>
      )}
    </div>
  );
}

// ── Tab: DevOps AI Agent ───────────────────────────────────────────────────
function renderInlineMarkdown(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, pIdx) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={pIdx} style={{ color: '#a3e635', fontWeight: 600 }}>{part.slice(2, -2)}</strong>;
    }
    
    const codeParts = part.split(/(`[^`]+`)/g);
    return codeParts.map((cPart, cIdx) => {
      if (cPart.startsWith('`') && cPart.endsWith('`')) {
        return (
          <code key={cIdx} style={{
            background: '#090d16',
            padding: '2px 5px',
            borderRadius: '4px',
            fontFamily: 'monospace',
            fontSize: '11px',
            color: '#a3e635',
            border: '1px solid #1e293b'
          }}>{cPart.slice(1, -1)}</code>
        );
      }
      return cPart;
    });
  });
}

function renderMarkdown(text: string) {
  if (!text) return null;
  const blocks = text.split(/(```[\s\S]*?```)/g);
  return blocks.map((block, bIdx) => {
    if (block.startsWith('```') && block.endsWith('```')) {
      const lines = block.slice(3, -3).trim().split('\n');
      const firstLine = lines[0].trim();
      const hasLang = /^[a-zA-Z0-9_-]+$/.test(firstLine);
      const codeLines = hasLang ? lines.slice(1) : lines;
      return (
        <pre key={bIdx} style={{
          background: '#090d16',
          padding: '12px',
          borderRadius: '6px',
          border: '1px solid #1e293b',
          fontFamily: 'monospace',
          fontSize: '12px',
          overflowX: 'auto',
          margin: '8px 0',
          color: '#e2e8f0',
          boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.5)'
        }}>
          <code>{codeLines.join('\n')}</code>
        </pre>
      );
    }

    const lines = block.split('\n');
    return (
      <div key={bIdx}>
        {lines.map((line, lIdx) => {
          const trimmed = line.trim();
          if (trimmed.startsWith('# ')) {
            return <h1 key={lIdx} style={{ fontSize: '18px', fontWeight: 700, margin: '12px 0 6px', color: '#a3e635' }}>{trimmed.slice(2)}</h1>;
          }
          if (trimmed.startsWith('## ')) {
            return <h2 key={lIdx} style={{ fontSize: '15px', fontWeight: 700, margin: '10px 0 6px', color: '#a3e635' }}>{trimmed.slice(3)}</h2>;
          }
          if (trimmed.startsWith('### ')) {
            return <h3 key={lIdx} style={{ fontSize: '13px', fontWeight: 700, margin: '8px 0 4px', color: '#e2e8f0' }}>{trimmed.slice(4)}</h3>;
          }
          if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
            return (
              <ul key={lIdx} style={{ margin: '4px 0 4px 16px', padding: 0 }}>
                <li style={{ color: '#cbd5e1' }}>{renderInlineMarkdown(trimmed.slice(2))}</li>
              </ul>
            );
          }
          if (/^\d+\.\s/.test(trimmed)) {
            const content = trimmed.replace(/^\d+\.\s/, '');
            return (
              <ol key={lIdx} style={{ margin: '4px 0 4px 16px', padding: 0 }}>
                <li style={{ color: '#cbd5e1' }}>{renderInlineMarkdown(content)}</li>
              </ol>
            );
          }
          if (trimmed === '') {
            return <div key={lIdx} style={{ height: '8px' }} />;
          }
          return <p key={lIdx} style={{ margin: '4px 0', color: '#cbd5e1' }}>{renderInlineMarkdown(line)}</p>;
        })}
      </div>
    );
  });
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

function TabAgent() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content: 'Hello! I am your Svaani DevOps & Debugging AI Assistant.\n\nI have access to live system diagnostics, including:\n- KPI metrics (total requests, error rates, latencies, AI call counts & costs)\n- Slowest API endpoints\n- Recent critical exceptions and system failures\n\nAsk me to analyze errors, explain system health, or suggest optimization actions.'
    }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  async function handleSend(text: string) {
    if (!text.trim() || loading) return;
    setErr('');
    const newMessages = [...messages, { role: 'user', content: text }] as Message[];
    setMessages(newMessages);
    setInput('');
    setLoading(true);

    try {
      const res = await api<{ response: string }>('/chat', {
        method: 'POST',
        body: JSON.stringify({ messages: newMessages }),
      });
      setMessages([...newMessages, { role: 'assistant', content: res.response }]);
    } catch (e: any) {
      setErr(e.message || 'Failed to communicate with AI agent.');
    } finally {
      setLoading(false);
    }
  }

  const SUGGESTED_QUERIES = [
    'Analyze recent system errors and tracebacks',
    'Summarize system performance metrics and KPIs',
    'What are the slowest endpoints on the server right now?',
    'Provide a general diagnostic overview'
  ];

  return (
    <div style={css.agentContainer}>
      <style>{`
        @keyframes pulse {
          0% { transform: scale(0.9); opacity: 0.6; }
          50% { transform: scale(1.1); opacity: 1; }
          100% { transform: scale(0.9); opacity: 0.6; }
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
        .pulse-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background-color: #a3e635;
          box-shadow: 0 0 8px #a3e635;
          animation: pulse 1.8s infinite ease-in-out;
        }
        .mini-spinner {
          width: 10px;
          height: 10px;
          border: 2px solid #64748b;
          border-top-color: transparent;
          border-radius: 50%;
          display: inline-block;
          animation: spin 0.8s linear infinite;
        }
      `}</style>

      <div style={css.agentHeader}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div className="pulse-dot"></div>
          <span style={{ fontWeight: 700, fontSize: 13, textTransform: 'uppercase', letterSpacing: '0.05em' }}>DevOps AI Agent</span>
          <span style={{ fontSize: 10, color: '#64748b', background: '#0f172a', padding: '2px 8px', borderRadius: 4, fontWeight: 600 }}>SARVAM-105B</span>
        </div>
        <span style={{ fontSize: 11, color: '#94a3b8' }}>Live System Diagnostics Connected</span>
      </div>

      <div style={css.chatWrapper}>
        <div style={css.messageList}>
          {messages.map((m, i) => (
            <div key={i} style={m.role === 'user' ? css.userMsgRow : css.assistantMsgRow}>
              <div style={m.role === 'user' ? css.userMsgBubble : css.assistantMsgBubble}>
                <div style={{ fontSize: 10, color: m.role === 'user' ? '#a3e635' : '#64748b', marginBottom: 4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  {m.role === 'user' ? 'Developer' : 'Agent'}
                </div>
                <div>{m.role === 'user' ? m.content : renderMarkdown(m.content)}</div>
              </div>
            </div>
          ))}
          {loading && (
            <div style={css.assistantMsgRow}>
              <div style={css.assistantMsgBubble}>
                <div style={{ fontSize: 10, color: '#64748b', marginBottom: 4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em' }}>Agent</div>
                <div style={{ color: '#64748b', display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                  <div className="mini-spinner"></div>
                  Analyzing live telemetry and diagnosing system state...
                </div>
              </div>
            </div>
          )}
          {err && (
            <div style={css.errBox}>
              <div style={{ fontWeight: 700, marginBottom: 4 }}>Agent Triage Failure</div>
              <div>{err}</div>
              {err.includes('SCRIBE_AGENT_API_KEY') && (
                <div style={{ marginTop: 10, padding: 8, background: '#3b0712', borderRadius: 4, fontSize: 11, color: '#fca5a5', border: '1px solid #991b1b' }}>
                  💡 <strong>System Action Required:</strong> Configure <code>SCRIBE_AGENT_API_KEY</code> on your backend (e.g. in your <code>.env</code> file) and reload the server to restore full agent operation.
                </div>
              )}
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div style={css.chatControls}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
            {SUGGESTED_QUERIES.map((s, idx) => (
              <button
                key={idx}
                disabled={loading}
                onClick={() => handleSend(s)}
                style={css.suggestionBtn}
              >
                🔍 {s}
              </button>
            ))}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSend(input);
            }}
            style={{ display: 'flex', gap: 8 }}
          >
            <input
              type="text"
              value={input}
              disabled={loading}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a diagnostic question (e.g. 'Why did the last request fail?')"
              style={css.agentInput}
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              style={{ ...css.btn, height: 36, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            >
              {loading ? 'Thinking…' : 'Send'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

// ── Tab: AI Analytics ──────────────────────────────────────────────────────
function TabAI() {
  const [data, setData] = useState<any>(null);
  const [fromDt, setFromDt] = useState('');
  const [toDt, setToDt] = useState('');
  const [err, setErr] = useState('');

  const load = useCallback(() => {
    const q = new URLSearchParams({ from_dt: fromDt, to_dt: toDt });
    api(`/ai-analytics?${q}`).then(setData).catch((e) => setErr(e.message));
  }, [fromDt, toDt]);

  useEffect(() => { load(); }, [load]);

  if (err) return <div style={css.errBox}>{err}</div>;
  if (!data) return <div style={css.spinner}>Loading…</div>;

  const summary = data.summary || {};
  const byAgent = data.by_agent || [];
  const byModel = data.by_model || [];
  const recent = data.recent_calls || [];

  return (
    <div>
      <SectionTitle>Summary</SectionTitle>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14, alignItems: 'flex-end' }}>
        <FilterInput label="From (ISO)" value={fromDt} onChange={setFromDt} />
        <FilterInput label="To (ISO)" value={toDt} onChange={setToDt} />
        <button style={css.btn} onClick={load}>Apply</button>
      </div>
      <div style={css.statGrid}>
        <StatCard label="Total Calls" value={summary.total_calls ?? 0} />
        <StatCard label="Success Rate" value={summary.success_rate_pct != null ? summary.success_rate_pct.toFixed(1) + '%' : '—'} />
        <StatCard label="Avg Latency" value={summary.avg_latency_ms != null ? summary.avg_latency_ms + ' ms' : '—'} />
        <StatCard label="p95 Latency" value={summary.p95_latency_ms != null ? summary.p95_latency_ms + ' ms' : '—'} />
        <StatCard label="Total Tokens" value={summary.total_tokens != null ? fmtNum(summary.total_tokens) : '—'} />
        <StatCard label="Total Cost" value={summary.total_cost_usd != null ? '$' + Number(summary.total_cost_usd).toFixed(4) : '—'} />
        <StatCard label="Avg Retries" value={summary.avg_retry_count != null ? summary.avg_retry_count.toFixed(2) : '—'} />
      </div>

      {/* Stage latency chart */}
      {data.latency_stages && (
        <>
          <SectionTitle>Pipeline Latency by Stage</SectionTitle>
          <StackedBarChart
            data={Object.fromEntries(
              Object.entries(data.latency_stages).map(([stage, v]: any) => [stage, v.p95_ms])
            )}
            labels={{}}
          />
        </>
      )}

      {byAgent.length > 0 && (
        <>
          <SectionTitle>By Agent</SectionTitle>
          <Table
            cols={['Agent', 'Calls', 'Success %', 'Avg ms', 'Total Tokens', 'Total Cost']}
            rows={byAgent.map((a: any) => [
              a.agent || 'unknown', a.calls,
              a.success_pct != null ? a.success_pct.toFixed(1) + '%' : '—',
              a.avg_latency_ms,
              a.total_tokens != null ? fmtNum(a.total_tokens) : '—',
              a.total_cost_usd != null ? '$' + Number(a.total_cost_usd).toFixed(4) : '—',
            ])}
          />
        </>
      )}

      {byModel.length > 0 && (
        <>
          <SectionTitle>By Model</SectionTitle>
          <Table
            cols={['Model', 'Calls', 'Avg ms', 'Total Tokens', 'Total Cost']}
            rows={byModel.map((m: any) => [
              m.model, m.calls, m.avg_latency_ms,
              m.total_tokens != null ? fmtNum(m.total_tokens) : '—',
              m.total_cost_usd != null ? '$' + Number(m.total_cost_usd).toFixed(4) : '—',
            ])}
          />
        </>
      )}

      {recent.length > 0 && (
        <>
          <SectionTitle>Recent Calls</SectionTitle>
          <Table
            cols={['Time', 'Model', 'Agent', 'Tokens', 'Cost', 'Latency', 'OK', 'Retries']}
            rows={recent.map((c: any) => [
              fmtDate(c.created_at), c.model, c.agent || '—', c.total_tokens ?? '—',
              c.cost_usd != null ? '$' + Number(c.cost_usd).toFixed(5) : '—',
              c.latency_ms != null ? c.latency_ms + ' ms' : '—',
              c.success ? '✓' : '✗', c.retry_count,
            ])}
          />
        </>
      )}
    </div>
  );
}

// ── Tab: Feedback ──────────────────────────────────────────────────────────
function TabFeedback() {
  const [data, setData] = useState<any>(null);
  const [page, setPage] = useState(1);
  const [err, setErr] = useState('');

  const load = useCallback(() => {
    api(`/feedback?page=${page}&limit=20`).then(setData).catch((e) => setErr(e.message));
  }, [page]);

  useEffect(() => { load(); }, [load]);

  if (err) return <div style={css.errBox}>{err}</div>;
  if (!data) return <div style={css.spinner}>Loading…</div>;

  const stats = data.stats || {};
  const entries = data.feedback || [];

  return (
    <div>
      <SectionTitle>Summary</SectionTitle>
      <div style={css.statGrid}>
        <StatCard label="Total Feedback" value={stats.total ?? 0} />
        <StatCard label="Avg Rating" value={stats.avg_rating != null ? Number(stats.avg_rating).toFixed(2) + ' / 5' : '—'} />
        {[1, 2, 3, 4, 5].map((r) => (
          <StatCard key={r} label={`★ ${r}`} value={stats.rating_distribution?.[String(r)] ?? 0} />
        ))}
      </div>
      <SectionTitle>Rating Distribution</SectionTitle>
      <StackedBarChart
        data={stats.rating_distribution || {}}
        labels={{ '1': '1 ★', '2': '2 ★', '3': '3 ★', '4': '4 ★', '5': '5 ★' }}
      />
      <SectionTitle>Entries</SectionTitle>
      <Table
        cols={['Time', 'User', 'Session', 'Rating', 'Feature', 'Comment']}
        rows={entries.map((f: any) => [
          fmtDate(f.created_at),
          f.user_id,
          f.session_id ? f.session_id.slice(0, 12) + '…' : '—',
          f.rating ? '★'.repeat(f.rating) : '—',
          f.feature || '—',
          (f.feedback_text || '').slice(0, 60),
        ])}
      />
      <Pager page={page} total={data.total || 0} limit={20} onPage={setPage} />
    </div>
  );
}

// ── Tab: Prompts & Models ──────────────────────────────────────────────────
function TabPromptsModels() {
  const [prompts, setPrompts] = useState<any[]>([]);
  const [models, setModels] = useState<any[]>([]);
  const [err, setErr] = useState('');
  const [newPrompt, setNewPrompt] = useState({ name: '', content: '', activate: false });

  const load = useCallback(() => {
    Promise.all([
      api('/prompts').catch(() => []),
      api('/models').catch(() => []),
    ]).then(([p, m]) => {
      setPrompts(p);
      setModels(m);
    }).catch((e) => setErr(e.message));
  }, []);

  useEffect(() => { load(); }, [load]);

  const createPrompt = async () => {
    try {
      await api('/prompts', {
        method: 'POST',
        body: JSON.stringify(newPrompt),
      });
      setNewPrompt({ name: '', content: '', activate: false });
      load();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  const activatePrompt = async (id: string) => {
    try {
      await api(`/prompts/${id}/activate`, { method: 'POST' });
      load();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  if (err) return <div style={css.errBox}>{err}</div>;

  return (
    <div>
      <SectionTitle>Prompt Versions</SectionTitle>
      <div style={{ marginBottom: 10 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <FilterInput label="Name" value={newPrompt.name} onChange={(v) => setNewPrompt({ ...newPrompt, name: v })} />
          <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontSize: 11, color: '#64748b' }}>Content</span>
            <textarea
              value={newPrompt.content}
              onChange={(e) => setNewPrompt({ ...newPrompt, content: e.target.value })}
              style={{ ...css.input, width: 260, height: 60, fontSize: 12 }}
              placeholder="Prompt template..."
            />
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 2 }}>
            <input
              type="checkbox"
              checked={newPrompt.activate}
              onChange={(e) => setNewPrompt({ ...newPrompt, activate: e.target.checked })}
            />
            <span style={{ fontSize: 11, color: '#94a3b8' }}>Activate</span>
          </label>
          <button style={css.btn} onClick={createPrompt}>Create</button>
        </div>
      </div>
      <Table
        cols={['ID', 'Name', 'Version', 'Active', 'Created By', 'Action']}
        rows={prompts.map((pv: any) => [
          pv.id,
          pv.name,
          pv.version,
          pv.active ? '✅' : '❌',
          pv.created_by || '—',
          <button key="act" style={css.smBtn} onClick={() => activatePrompt(pv.id)}>Activate</button>,
        ])}
      />

      <SectionTitle>Model Versions</SectionTitle>
      <Table
        cols={['Model ID', 'Name', 'Version']}
        rows={models.map((m: any) => [m.id, m.name, m.version])}
      />
    </div>
  );
}

// ── Tab: Feature Flags ─────────────────────────────────────────────────────
function TabFlags() {
  const [flags, setFlags] = useState<any>(null);
  const [err, setErr] = useState('');
  const [newFlag, setNewFlag] = useState({ key: '', enabled: true, value: '{}' });

  const load = () => {
    api('/feature-flags').then(setFlags).catch((e) => setErr(e.message));
  };
  useEffect(() => { load(); }, []);

  const setFlag = async () => {
    try {
      let parsed = {};
      try {
        parsed = JSON.parse(newFlag.value);
      } catch { /* leave as string */ }
      await api('/feature-flags', {
        method: 'POST',
        body: JSON.stringify({ key: newFlag.key, enabled: newFlag.enabled, value: parsed }),
      });
      setNewFlag({ key: '', enabled: true, value: '{}' });
      load();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  if (err) return <div style={css.errBox}>{err}</div>;
  if (!flags) return <div style={css.spinner}>Loading…</div>;

  return (
    <div>
      <SectionTitle>Runtime Feature Flags</SectionTitle>
      <div style={{ marginBottom: 10, display: 'flex', gap: 8, alignItems: 'flex-end' }}>
        <FilterInput label="Key" value={newFlag.key} onChange={(v) => setNewFlag({ ...newFlag, key: v })} />
        <label style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 2 }}>
          <input
            type="checkbox"
            checked={newFlag.enabled}
            onChange={(e) => setNewFlag({ ...newFlag, enabled: e.target.checked })}
          />
          <span style={{ fontSize: 11, color: '#94a3b8' }}>Enabled</span>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ fontSize: 11, color: '#64748b' }}>Value (JSON)</span>
          <input
            style={{ ...css.input, width: 160, fontSize: 12 }}
            value={newFlag.value}
            onChange={(e) => setNewFlag({ ...newFlag, value: e.target.value })}
          />
        </label>
        <button style={css.btn} onClick={setFlag}>Set</button>
      </div>
      <Table
        cols={['Key', 'Enabled', 'Value']}
        rows={flags.runtime.map((f: any) => [f.key, f.enabled ? '✅' : '❌', JSON.stringify(f.value)])}
      />
    </div>
  );
}

// ── Tab: Reviews & Improvements ────────────────────────────────────────────
function TabReviews() {
  const [reviews, setReviews] = useState<any[]>([]);
  const [improvements, setImprovements] = useState<any[]>([]);
  const [err, setErr] = useState('');

  const load = useCallback(() => {
    Promise.all([
      api('/admin/reviews').catch(() => []),
      api('/admin/improvements').catch(() => []),
    ]).then(([r, i]) => {
      setReviews(r);
      setImprovements(i);
    }).catch((e) => setErr(e.message));
  }, []);

  useEffect(() => { load(); }, [load]);

  const updateReview = async (id: string, status: string) => {
    try {
      await api(`/admin/reviews/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      });
      load();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  if (err) return <div style={css.errBox}>{err}</div>;

  return (
    <div>
      <SectionTitle>Doctor Reviews (Admin Triage)</SectionTitle>
      <Table
        cols={['ID', 'Session', 'Rating', 'Error Categories', 'Status', 'Action']}
        rows={reviews.map((r: any) => [
          r.id,
          r.session_id,
          r.rating,
          (r.error_categories || []).join(', '),
          r.admin_status || 'new',
          <div style={{ display: 'flex', gap: 4 }}>
            <button style={css.smBtn} onClick={() => updateReview(r.id, 'approved')}>Approve</button>
            <button style={css.smBtn} onClick={() => updateReview(r.id, 'rejected')}>Reject</button>
          </div>,
        ])}
      />
      <SectionTitle>Improvement Pipeline</SectionTitle>
      <Table
        cols={['ID', 'Source', 'Stage', 'Assigned To', 'Created']}
        rows={improvements.map((i: any) => [
          i.id,
          i.source_review_id,
          i.stage,
          i.assigned_to || '—',
          fmtDate(i.created_at),
        ])}
      />
    </div>
  );
}

// ── Tab: A/B Metrics ───────────────────────────────────────────────────────
function TabABMetrics() {
  const [prompts, setPrompts] = useState<any[]>([]);
  const [selectedPrompt, setSelectedPrompt] = useState('');
  const [metrics, setMetrics] = useState<any>(null);
  const [err, setErr] = useState('');

  const loadPrompts = () => {
    api('/prompts').then((list: any[]) => {
      const names = [...new Set(list.map((p: any) => p.name))];
      setPrompts(names);
      if (names.length && !selectedPrompt) setSelectedPrompt(names[0]);
    }).catch((e) => setErr(e.message));
  };

  const loadMetrics = () => {
    if (!selectedPrompt) return;
    api(`/admin/prompts/${selectedPrompt}/ab/metrics`)
      .then(setMetrics)
      .catch((e) => setErr(e.message));
  };

  useEffect(() => { loadPrompts(); }, []);
  useEffect(() => { loadMetrics(); }, [selectedPrompt]);

  return (
    <div>
      <SectionTitle>Prompt A/B Test Metrics</SectionTitle>
      {err && <div style={css.errBox}>{err}</div>}
      <div style={{ display: 'flex', gap: 10, marginBottom: 14, alignItems: 'flex-end' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ fontSize: 11, color: '#64748b' }}>Prompt</span>
          <select
            value={selectedPrompt}
            onChange={(e) => setSelectedPrompt(e.target.value)}
            style={{ ...css.input, width: 180, padding: '4px 8px', fontSize: 12 }}
          >
            {prompts.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </label>
        <button style={css.btn} onClick={loadMetrics}>Load</button>
      </div>
      {metrics && (
        <div>
          <div style={{ display: 'flex', gap: 20 }}>
            {Object.entries(metrics.arms).map(([arm, data]: any) => (
              <div key={arm} style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, color: '#a3e635', marginBottom: 4 }}>Arm {arm.toUpperCase()}</div>
                <div style={{ fontSize: 12, color: '#cbd5e1' }}>N: {data.n}</div>
                <div style={{ fontSize: 12, color: '#a3e635' }}>Helpful: {data.helpful}</div>
                <div style={{ fontSize: 12, color: '#f87171' }}>Needs Improvement: {data.needs_improvement}</div>
                <div style={{ marginTop: 6 }}>
                  <Bar value={data.helpful} max={data.n} color="#a3e635" />
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 16, fontSize: 12, color: '#94a3b8' }}>
            Total consults in test: {metrics.total}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Login screen ──────────────────────────────────────────────────────────
function LoginScreen({ onLogin }: { onLogin: (token: string) => void }) {
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const r = await fetch('/admin1/api/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      });
      const j = await r.json();
      if (!r.ok || !j.ok) {
        setError('Invalid password.');
        return;
      }
      localStorage.setItem(TOKEN_KEY, j.token);
      onLogin(j.token);
    } catch {
      setError('Connection failed.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={css.loginWrap}>
      <div style={css.loginCard}>
        <div style={{ fontSize: 28, fontWeight: 800, color: '#a3e635', marginBottom: 4 }}>𝓢 Svaani</div>
        <div style={{ fontSize: 13, color: '#64748b', marginBottom: 28 }}>Internal Admin — Production Observability</div>
        <form onSubmit={submit}>
          <label style={{ display: 'block', marginBottom: 16 }}>
            <span style={{ fontSize: 12, color: '#94a3b8', display: 'block', marginBottom: 6 }}>Admin Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={css.loginInput}
              placeholder="Enter password"
              autoFocus
            />
          </label>
          {error && <div style={{ color: '#f87171', fontSize: 12, marginBottom: 10 }}>{error}</div>}
          <button type="submit" style={css.loginBtn} disabled={loading || !password}>
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Main AdminPage ────────────────────────────────────────────────────────
type Tab =
  | 'overview' | 'doctors' | 'health' | 'logs' | 'errors' | 'ai'
  | 'feedback' | 'prompts' | 'flags' | 'reviews' | 'ab' | 'agent';

export function AdminPage() {
  const [token, setToken] = useState<string | null>(localStorage.getItem(TOKEN_KEY));
  const [tab, setTab] = useState<Tab>('overview');

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
  }

  if (!token) return <LoginScreen onLogin={setToken} />;

  const TABS: [Tab, string][] = [
    ['overview', 'Overview'],
    ['agent', 'DevOps Agent'],
    ['doctors', 'Doctors'],
    ['health', 'System Health'],
    ['logs', 'Logs'],
    ['errors', 'Errors'],
    ['ai', 'AI Analytics'],
    ['feedback', 'Feedback'],
    ['prompts', 'Prompts/Models'],
    ['flags', 'Feature Flags'],
    ['reviews', 'Reviews'],
    ['ab', 'A/B Tests'],
  ];

  return (
    <div style={css.shell}>
      <header style={css.header}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 20, fontWeight: 800, color: '#a3e635' }}>𝓢</span>
          <span style={{ fontWeight: 700, color: '#e2e8f0' }}>Svaani Admin</span>
          <span style={css.badge}>INTERNAL</span>
        </div>
        <button style={css.smBtn} onClick={logout}>Sign out</button>
      </header>

      <div style={css.nav}>
        {TABS.map(([id, label]) => (
          <button
            key={id}
            style={{ ...css.navBtn, ...(tab === id ? css.navBtnActive : {}) }}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      <main style={css.main}>
        {tab === 'overview' && <TabOverview />}
        {tab === 'agent' && <TabAgent />}
        {tab === 'doctors' && <TabDoctors />}
        {tab === 'health' && <TabHealth />}
        {tab === 'logs' && <TabLogs />}
        {tab === 'errors' && <TabErrors />}
        {tab === 'ai' && <TabAI />}
        {tab === 'feedback' && <TabFeedback />}
        {tab === 'prompts' && <TabPromptsModels />}
        {tab === 'flags' && <TabFlags />}
        {tab === 'reviews' && <TabReviews />}
        {tab === 'ab' && <TabABMetrics />}
      </main>
    </div>
  );
}

// ── Helpers & styles (unchanged) ──────────────────────────────────────────
function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' });
}

function fmtNum(n: number): string {
  return n >= 1_000_000 ? (n / 1_000_000).toFixed(1) + 'M' : n >= 1_000 ? (n / 1_000).toFixed(1) + 'K' : String(n);
}

function severityColor(s: string): string {
  return s === 'critical' ? '#f87171' : s === 'warning' ? '#fb923c' : '#facc15';
}

const css: Record<string, React.CSSProperties> = {
  shell: { minHeight: '100vh', background: '#0f172a', color: '#e2e8f0', fontFamily: 'system-ui, sans-serif', display: 'flex', flexDirection: 'column' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 24px', borderBottom: '1px solid #1e293b', background: '#0f172a', position: 'sticky', top: 0, zIndex: 10 },
  badge: { fontSize: 11, color: '#475569', background: '#1e293b', padding: '2px 8px', borderRadius: 4 },
  nav: { display: 'flex', gap: 2, padding: '10px 24px 0', borderBottom: '1px solid #1e293b', background: '#0f172a' },
  navBtn: { padding: '8px 16px', fontSize: 13, fontWeight: 500, color: '#64748b', background: 'transparent', border: 'none', borderBottom: '2px solid transparent', cursor: 'pointer', transition: 'color 0.15s' },
  navBtnActive: { color: '#a3e635', borderBottomColor: '#a3e635' },
  main: { flex: 1, padding: 24, maxWidth: 1200, width: '100%', margin: '0 auto' },
  sectionTitle: { fontSize: 13, fontWeight: 600, color: '#94a3b8', margin: '20px 0 10px', textTransform: 'uppercase', letterSpacing: '0.05em' },
  statGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 12, marginBottom: 8 },
  statCard: { background: '#1e293b', borderRadius: 8, padding: '14px 16px', border: '1px solid #334155' },
  th: { padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#64748b', borderBottom: '1px solid #1e293b', textTransform: 'uppercase', letterSpacing: '0.04em' },
  td: { padding: '8px 12px', fontSize: 12, color: '#cbd5e1', borderBottom: '1px solid #1e293b' },
  btn: { padding: '6px 14px', fontSize: 12, fontWeight: 600, background: '#a3e635', color: '#0f172a', border: 'none', borderRadius: 6, cursor: 'pointer' },
  smBtn: { padding: '4px 10px', fontSize: 11, fontWeight: 500, background: '#1e293b', color: '#94a3b8', border: '1px solid #334155', borderRadius: 4, cursor: 'pointer' },
  pgBtn: { padding: '4px 12px', fontSize: 12, background: '#1e293b', color: '#94a3b8', border: '1px solid #334155', borderRadius: 4, cursor: 'pointer' },
  input: { background: '#1e293b', border: '1px solid #334155', borderRadius: 4, color: '#e2e8f0', outline: 'none' },
  errBox: { background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 6, padding: 12, color: '#fca5a5', fontSize: 13 },
  errRow: { padding: '10px 14px', marginBottom: 4, background: '#1e293b', borderRadius: 4 },
  stackTrace: { marginTop: 8, padding: 10, background: '#0f172a', borderRadius: 4, fontSize: 11, color: '#94a3b8', overflow: 'auto', maxHeight: 200 },
  spinner: { color: '#64748b', fontSize: 13, padding: 20 },
  loginWrap: { minHeight: '100vh', background: '#0f172a', display: 'flex', alignItems: 'center', justifyContent: 'center' },
  loginCard: { background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: '36px 40px', width: 340 },
  loginInput: { width: '100%', padding: '10px 14px', background: '#0f172a', border: '1px solid #334155', borderRadius: 6, color: '#e2e8f0', fontSize: 14, outline: 'none', boxSizing: 'border-box' },
  loginBtn: { width: '100%', padding: '10px 0', background: '#a3e635', color: '#0f172a', border: 'none', borderRadius: 6, fontWeight: 700, fontSize: 14, cursor: 'pointer' },
  agentContainer: { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, display: 'flex', flexDirection: 'column', height: 'calc(100vh - 200px)', minHeight: 500, overflow: 'hidden' },
  agentHeader: { background: '#0f172a', padding: '12px 16px', borderBottom: '1px solid #334155', display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  chatWrapper: { flex: 1, display: 'flex', flexDirection: 'column', background: '#0f172a', overflow: 'hidden' },
  messageList: { flex: 1, padding: 16, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 12 },
  userMsgRow: { display: 'flex', justifyContent: 'flex-end' },
  assistantMsgRow: { display: 'flex', justifyContent: 'flex-start' },
  userMsgBubble: { background: '#1e293b', border: '1px solid #334155', borderRadius: '8px 8px 0 8px', padding: '10px 14px', maxWidth: '80%', fontSize: 13, color: '#cbd5e1', boxShadow: '0 2px 4px rgba(0,0,0,0.1)' },
  assistantMsgBubble: { background: 'rgba(30, 41, 59, 0.5)', border: '1px solid #1e293b', borderRadius: '8px 8px 8px 0', padding: '10px 14px', maxWidth: '80%', fontSize: 13, color: '#e2e8f0', boxShadow: '0 2px 4px rgba(0,0,0,0.05)' },
  chatControls: { padding: 16, background: '#1e293b', borderTop: '1px solid #334155' },
  suggestionBtn: { background: '#0f172a', border: '1px solid #334155', borderRadius: 6, padding: '6px 12px', fontSize: 11, color: '#94a3b8', cursor: 'pointer', transition: 'all 0.2s', marginRight: 4, marginBottom: 4 },
  agentInput: { flex: 1, background: '#0f172a', border: '1px solid #334155', borderRadius: 6, color: '#e2e8f0', padding: '8px 12px', fontSize: 13, outline: 'none' },
};