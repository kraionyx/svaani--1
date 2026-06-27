import { useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useEffectiveRole } from '../app/useRole';
import { useAuth } from '../auth';
import { useStore } from '../store';
import { Activity, LayoutDashboard, FileText, Users, Settings, Shield, Menu, Bell, ChevronsUpDown, Sparkles, BadgeCheck, CreditCard, LogOut } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  Sidebar as ShadcnSidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuItem,
  useSidebar
} from '@/components/ui/sidebar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
  DropdownMenuGroup,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";

function formatSessionDate(isoString?: string | null) {
  if (!isoString) return '';
  const d = new Date(isoString);
  if (isNaN(d.getTime())) return '';
  const datePart = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  const timePart = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  return `${datePart}, ${timePart}`;
}

export function Sidebar() {
  const s = useStore();
  const role = useEffectiveRole();
  const { toggleSidebar } = useSidebar();
  const { session, signOut } = useAuth();
  const location = useLocation();

  const user = session?.user;
  const fullName = user?.user_metadata?.full_name || user?.email?.split('@')[0] || 'Unknown User';
  const email = user?.email || 'No email provided';

  useEffect(() => {
    if (session) s.loadHistory();
  }, [session]);

  const MAIN_NAV = [
    { to: '/dashboard', label: 'Scribe Console', icon: Activity },
    { to: '/templates', label: 'Templates', icon: FileText },
    { to: '/patients', label: 'Patients', icon: Users },
    { to: '/reports', label: 'Reports', icon: LayoutDashboard },
    { to: '/admin', label: 'Admin', icon: Shield, adminOnly: true },
  ];

  const checkIsActive = (path: string) => location.pathname.startsWith(path);

  return (
    <ShadcnSidebar collapsible="icon" className="border-r-0 shadow-[4px_0_24px_rgba(0,0,0,0.02)] bg-white font-sans text-slate-700 z-40">
      <SidebarHeader className="pt-4 px-4">
        <div className="flex items-center justify-between group-data-[collapsible=icon]:justify-center mb-2">
          <div className="font-bold text-2xl text-slate-800 tracking-tight group-data-[collapsible=icon]:hidden">
            Svaani<span className="text-sky-500">.</span>
          </div>
          <button type="button" onClick={toggleSidebar} className="p-2 rounded-xl hover:bg-slate-50 text-slate-400 hover:text-slate-600 transition-colors">
            <Menu size={22} strokeWidth={2.5} />
          </button>
        </div>
      </SidebarHeader>

      <SidebarContent className="flex-1 overflow-y-auto hidden-scrollbar p-3 group-data-[collapsible=icon]:px-2">
        {/* Main Section */}
        <div className="mb-4">
          <div className="text-[10px] font-bold tracking-widest text-slate-400 mb-2 px-3 flex items-center gap-2">
            <div className="group-data-[collapsible=icon]:hidden flex items-center gap-2 uppercase">
              Dashboard
            </div>
            <div className="hidden group-data-[collapsible=icon]:block w-full text-center">
              <Activity size={14} className="mx-auto text-slate-300" />
            </div>
          </div>

          <SidebarMenu className="gap-1">
            {MAIN_NAV.filter((n) => !n.adminOnly || role === 'admin').map((n) => {
              const isActive = checkIsActive(n.to);
              return (
                <SidebarMenuItem key={n.to}>
                  <Tooltip delayDuration={0}>
                    <TooltipTrigger asChild>
                      <Link to={n.to} className={`flex items-center gap-3 px-3 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:justify-center py-2.5 rounded-xl transition-all w-full justify-between ${isActive ? 'bg-sky-50 text-sky-700 font-semibold shadow-sm' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-800 active:bg-slate-100'}`}>
                        <div className="flex items-center gap-3 group-data-[collapsible=icon]:gap-0">
                          <n.icon size={20} strokeWidth={isActive ? 2.5 : 2} className={isActive ? "text-sky-600" : "text-slate-400"} />
                          <span className="text-[14px] group-data-[collapsible=icon]:hidden">{n.label}</span>
                        </div>
                      </Link>
                    </TooltipTrigger>
                    <TooltipContent side="right" className="group-data-[state=expanded]:hidden bg-slate-800 text-white font-medium px-2 py-1 text-xs">
                      {n.label}
                    </TooltipContent>
                  </Tooltip>
                </SidebarMenuItem>
              );
            })}
          </SidebarMenu>
        </div>

        {/* Recents Section */}
        {session && s.history.length > 0 && (
          <div className="mt-4 pb-4">
            <div className="text-[10px] font-bold tracking-widest text-slate-400 mb-2 px-3 flex items-center justify-between uppercase group-data-[collapsible=icon]:hidden">
              <span>Recents</span>
              <button onClick={() => s.loadHistory()} className="hover:text-slate-600 transition-colors">↻</button>
            </div>
            <SidebarMenu className="gap-1 group-data-[collapsible=icon]:hidden">
              {s.history.map((h) => (
                <SidebarMenuItem key={h.session_id}>
                  <button
                    onClick={() => s.openSession(h.session_id)}
                    className={`flex flex-col gap-1 px-3 py-2 rounded-xl transition-all w-full text-left ${h.session_id === s.sessionId ? 'bg-sky-50 border border-sky-100 shadow-sm' : 'hover:bg-slate-50 border border-transparent hover:border-slate-100'}`}
                  >
                    <div className="flex items-center justify-between w-full">
                      <span className="text-[12px] font-semibold text-slate-700 truncate mr-2">
                        {h.session_id.replace('sess-', '')}
                      </span>
                      {h.template_id && (
                        <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-md bg-slate-100 text-slate-500 uppercase shrink-0">
                          {h.template_id}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center justify-between w-full">
                      <span className="text-[10px] text-slate-400">
                        {formatSessionDate(h.created_at)}
                      </span>
                      <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full capitalize shrink-0 ${(h.state as string) === 'final' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>
                        {h.state.replace(/_/g, ' ')}
                      </span>
                    </div>
                  </button>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </div>
        )}
      </SidebarContent>

      <SidebarFooter className="p-4 group-data-[collapsible=icon]:p-1 pb-4">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <div className="border border-slate-200 bg-slate-50/70 rounded-full p-2 group-data-[collapsible=icon]:p-0 flex items-center justify-between cursor-pointer hover:bg-slate-100 hover:shadow-sm transition-all group-data-[collapsible=icon]:bg-transparent group-data-[collapsible=icon]:border-transparent group-data-[collapsible=icon]:shadow-none group-data-[collapsible=icon]:justify-center">
              <div className="flex items-center gap-3 group-data-[collapsible=icon]:gap-0 min-w-0">
                <div className="w-10 h-10 group-data-[collapsible=icon]:w-8 group-data-[collapsible=icon]:h-8 rounded-full overflow-hidden flex-shrink-0 border border-slate-200 shadow-sm bg-white flex items-center justify-center text-sky-600 font-bold uppercase text-lg group-data-[collapsible=icon]:text-sm">
                  {fullName.charAt(0)}
                </div>
                <div className="flex flex-col group-data-[collapsible=icon]:hidden overflow-hidden pr-2 min-w-0 text-left">
                  <span className="text-[13px] font-semibold text-slate-800 truncate">{fullName}</span>
                  <span className="text-[10px] text-slate-500 font-medium truncate">{email}</span>
                </div>
              </div>
              <ChevronsUpDown size={16} className="text-slate-600 mr-2 flex-shrink-0 group-data-[collapsible=icon]:hidden" />
            </div>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-72 mb-2 rounded-xl bg-white shadow-lg border border-slate-200" align="end" side="right" sideOffset={8}>
            <DropdownMenuLabel className="p-0 font-normal">
              <div className="flex items-center gap-3 px-2 py-2 text-left text-sm">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-sky-100 text-sky-700 font-bold uppercase text-lg">
                  {fullName.charAt(0)}
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight min-w-0">
                  <span className="truncate font-semibold text-slate-800">{fullName}</span>
                  <span className="truncate text-xs text-slate-500">{email}</span>
                </div>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuItem className="cursor-pointer rounded-lg">
                <Sparkles className="mr-2 h-4 w-4" />
                <span>Upgrade to Pro</span>
              </DropdownMenuItem>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuItem asChild className="cursor-pointer rounded-lg">
                <Link to="/profile" className="flex items-center w-full">
                  <Users className="mr-2 h-4 w-4" />
                  <span>Profile</span>
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem className="cursor-pointer rounded-lg">
                <BadgeCheck className="mr-2 h-4 w-4" />
                <span>Account</span>
              </DropdownMenuItem>
              <DropdownMenuItem className="cursor-pointer rounded-lg">
                <CreditCard className="mr-2 h-4 w-4" />
                <span>Billing</span>
              </DropdownMenuItem>
              <DropdownMenuItem asChild className="cursor-pointer rounded-lg">
                <Link to="/settings" className="flex items-center w-full">
                  <Settings className="mr-2 h-4 w-4" />
                  <span>Settings</span>
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem className="cursor-pointer rounded-lg">
                <Bell className="mr-2 h-4 w-4" />
                <span>Notifications</span>
              </DropdownMenuItem>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem className="cursor-pointer rounded-lg text-red-600 focus:text-red-600 focus:bg-red-50" onClick={() => signOut()}>
              <LogOut className="mr-2 h-4 w-4" />
              <span>Log out</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarFooter>

    </ShadcnSidebar>
  );
}
