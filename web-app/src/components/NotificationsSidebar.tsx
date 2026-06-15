
export interface Notification {
  id: number;
  m: string;
  e: boolean;
  time: Date;
}

interface Props {
  open: boolean;
  notifications: Notification[];
  onClose: () => void;
  onClear: () => void;
}

export function NotificationsSidebar({ open, notifications, onClose, onClear }: Props) {
  if (!open) return null;

  return (
    <div 
      style={{
        width: '350px',
        background: 'var(--surface)', borderLeft: '1px solid var(--border-soft)',
        display: 'flex', flexDirection: 'column',
        height: 'calc(100vh - 64px)',
        position: 'sticky', top: '64px',
        flexShrink: 0
      }}
    >
      <div style={{ padding: 'var(--space-md)', borderBottom: '1px solid var(--border-soft)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ margin: 0 }}>Notifications</h3>
          <button className="btn ghost sm" onClick={onClose} style={{ padding: '0 8px', fontSize: '1.2rem' }}>✕</button>
        </div>
        
        <div style={{ flex: 1, overflowY: 'auto', padding: 'var(--space-md)' }}>
          {notifications.length === 0 ? (
            <div className="hint" style={{ textAlign: 'center', marginTop: 'var(--space-xl)' }}>No notifications</div>
          ) : (
            notifications.map(n => (
              <div key={n.id} style={{ 
                display: 'flex', gap: '12px',
                padding: '1.25rem', 
                marginBottom: 'var(--space-sm)', 
                background: n.e ? 'var(--critical)' : 'var(--surface)',
                border: n.e ? '1px solid var(--critical)' : '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)',
                color: n.e ? 'white' : 'var(--text)',
                boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -4px rgba(0, 0, 0, 0.1)'
              }}>
                <div style={{ flexShrink: 0, marginTop: '2px' }}>
                  {n.e ? (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                  ) : (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                  )}
                </div>
                <div>
                  <div style={{ fontSize: '0.875rem', fontWeight: 500, lineHeight: 1.4 }}>{n.m}</div>
                  <div className="hint" style={{ fontSize: '0.875rem', marginTop: '4px', opacity: 0.9, color: n.e ? 'rgba(255,255,255,0.9)' : 'var(--muted)' }}>{n.time.toLocaleTimeString()}</div>
                </div>
              </div>
            ))
          )}
        </div>

        {notifications.length > 0 && (
          <div style={{ padding: 'var(--space-md)', borderTop: '1px solid var(--border-soft)', display: 'flex', justifyContent: 'center' }}>
            <button 
              className="btn ghost" 
              onClick={onClear}
              style={{ borderRadius: '999px', width: '100%' }}
            >
              Clear all
            </button>
          </div>
        )}
      </div>
  );
}
