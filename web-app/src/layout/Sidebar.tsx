import { NavLink } from 'react-router-dom';
import { useEffectiveRole } from '../app/useRole';
import { Activity, LayoutDashboard, FileText, Users, Settings, UserCircle, Shield, ChevronDown, ChevronUp, Check } from 'lucide-react';
import {
  Sidebar as ShadcnSidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar
} from '@/components/ui/sidebar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

export function Sidebar() {
  const role = useEffectiveRole();
  const { toggleSidebar } = useSidebar();

  const NAV = [
    { to: '/dashboard', label: 'Scribe Console', icon: Activity },
    { to: '/templates', label: 'Templates', icon: FileText },
    { to: '/patients', label: 'Patients', icon: Users },
    { to: '/reports', label: 'Reports', icon: LayoutDashboard },
    { to: '/settings', label: 'Settings', icon: Settings },
    { to: '/profile', label: 'Profile', icon: UserCircle },
    { to: '/admin', label: 'Admin', icon: Shield, adminOnly: true },
  ];

  return (
    <ShadcnSidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton size="lg" className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground">
                  <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                    <span className="font-bold font-serif text-lg leading-none">S</span>
                  </div>
                  <div className="flex flex-col gap-0.5 leading-none text-left">
                    <span className="font-semibold">Svaani</span>
                    <span className="text-xs text-muted-foreground">AI Medical Scribe</span>
                  </div>
                  <ChevronDown className="ml-auto size-4 shrink-0" />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="w-[--radix-dropdown-menu-trigger-width] min-w-56 rounded-lg" align="start" side="bottom" sideOffset={4}>
                <DropdownMenuItem onClick={toggleSidebar}>
                  <Check className="mr-2 h-4 w-4 opacity-0" />
                  Toggle Sidebar
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Application</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.filter((n) => !n.adminOnly || role === 'admin').map((n) => (
                <SidebarMenuItem key={n.to}>
                  <SidebarMenuButton asChild tooltip={n.label}>
                    <NavLink to={n.to} className={({ isActive }) => (isActive ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground' : 'text-sidebar-foreground')}>
                      <n.icon />
                      <span>{n.label}</span>
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton size="lg" className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground">
                  <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                    <UserCircle className="size-5" />
                  </div>
                  <div className="flex flex-col gap-0.5 leading-none text-left">
                    <span className="font-semibold uppercase text-xs tracking-wider">{role}</span>
                    <span className="text-xs text-muted-foreground truncate">Logged In</span>
                  </div>
                  <ChevronUp className="ml-auto size-4 shrink-0" />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="w-[--radix-dropdown-menu-trigger-width] min-w-56 rounded-lg" align="start" side="top" sideOffset={4}>
                <DropdownMenuItem>
                  <span>Role: {role}</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />
    </ShadcnSidebar>
  );
}
