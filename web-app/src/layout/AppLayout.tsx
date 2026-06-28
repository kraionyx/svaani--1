import { Suspense, useEffect, useState } from 'react';
import { Outlet } from 'react-router-dom';
import * as API from '../api';
import { useStore } from '../store';
import { onToast, toast } from '../toast';
import { Sidebar } from './Sidebar';
import { SidebarProvider, SidebarInset, SidebarTrigger } from '@/components/ui/sidebar';

export function AppLayout() {
  const s = useStore();
  const [toastMsg, setToastMsg] = useState<{ m: string; e: boolean } | null>(null);

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
    <SidebarProvider>
      <Sidebar />
      <SidebarInset className="w-full h-screen flex flex-col overflow-hidden bg-[#eef1f7]">
        <div className="md:hidden absolute top-4 left-4 right-4 z-50 flex items-center gap-3">
          <SidebarTrigger />
          <div className="font-bold text-[20px] text-slate-800 tracking-tight ml-1">
            Svaani<span className="text-sky-500">.</span>
          </div>
        </div>
        <div className="app-content flex-1 overflow-hidden relative flex flex-col pt-14 md:pt-0">
          <Suspense fallback={<div className="route-loading"><span className="route-spinner" aria-hidden="true" /> Waking up Svaani…</div>}>
            <Outlet />
          </Suspense>
        </div>
      </SidebarInset>
      {toastMsg && <div className={`toast ${toastMsg.e ? 'err' : ''}`}>{toastMsg.m}</div>}
    </SidebarProvider>
  );
}
