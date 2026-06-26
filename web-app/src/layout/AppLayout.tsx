// Persistent application shell rendered around every route: top bar, primary nav sidebar,
// breadcrumb trail, and the routed <Outlet/>. Also owns app-wide concerns lifted out of the
// old monolith: one-time health/template bootstrap, the toast surface, and the theme studio.
import { Suspense, useEffect, useState } from 'react';
import { Outlet } from 'react-router-dom';
import * as API from '../api';
import { useStore } from '../store';
import { onToast, toast } from '../toast';
import { ThemeStudio } from '../components/ThemeStudio';
import { TopBar } from './TopBar';
import { Sidebar } from './Sidebar';
import { Breadcrumbs } from './Breadcrumbs';

export function AppLayout() {
  const s = useStore();
  const [toastMsg, setToastMsg] = useState<{ m: string; e: boolean } | null>(null);
  const [studioOpen, setStudioOpen] = useState(false);

  useEffect(() => {
    onToast((m, e) => { setToastMsg({ m, e }); setTimeout(() => setToastMsg(null), e ? 6500 : 3000); });
    API.getHealth().then((h) => s.set({ health: h })).catch(() => toast('backend unreachable on :8000', true));
    API.listTemplates().then((t) => {
      s.set({ templates: t });
      if (t.find((x) => x.template_id === 'ent')) s.set({ templateId: 'ent' });
      else if (t[0]) s.set({ templateId: t[0].template_id });
    }).catch(() => { });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="app-shell">
      <TopBar onOpenStudio={setStudioOpen} />
      <div className="app-body">
        <Sidebar />
        <div className="app-content">
          <Breadcrumbs />
          <Suspense fallback={<div className="route-loading"><span className="route-spinner" aria-hidden="true" /> Loading…</div>}>
            <Outlet />
          </Suspense>
        </div>
      </div>
      {studioOpen && <ThemeStudio onClose={() => setStudioOpen(false)} />}
      {toastMsg && <div className={`toast ${toastMsg.e ? 'err' : ''}`}>{toastMsg.m}</div>}
    </div>
  );
}
