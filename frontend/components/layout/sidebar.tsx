'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import * as LucideIcons from 'lucide-react';
import {
  LayoutDashboard,
  MessageSquare,
  Wrench,
  Brain,
  Bot,
  Settings,
  Menu,
  X,
  RotateCcw,
  Loader2,
  Plug,
  Bug,
  CalendarClock,
  Clock,
  Network,
  Heart,
  Puzzle,
} from 'lucide-react';
import { useChatStore } from '@/stores/chat-store';
import { useAuthStore } from '@/stores/auth-store';
import { TamagotchiWidget } from '@/components/tamagotchi/tamagotchi-widget';
import { translations } from '@/lib/translations';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { ACMMark, SignalStripe } from '@/components/ui/acm-mark';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const t = translations.navigation;

// Core nav items — only features built into OpenACM core
const coreNavItems = [
  { href: '/dashboard', label: t.dashboard, icon: LayoutDashboard },
  { href: '/chat', label: t.chat, icon: MessageSquare },
  { href: '/swarms', label: t.swarms, icon: Network },
  { href: '/tamagotchi', label: t.tamagotchi, icon: Heart },
  { href: '/routines', label: t.routines, icon: CalendarClock },
  { href: '/cron', label: t.cron, icon: Clock },
  { href: '/tools', label: t.tools, icon: Wrench },
  { href: '/skills', label: t.skills, icon: Brain },
  { href: '/agents', label: t.agents, icon: Bot },
  { href: '/mcp', label: t.mcp, icon: Plug },
  { href: '/debug', label: t.debug, icon: Bug },
  { href: '/config', label: t.config, icon: Settings },
];

interface PluginNavItem {
  path: string;
  label: string;
  icon: string;       // lucide icon name, e.g. "Newspaper"
  section?: string;   // "main" | "bottom"
  badge?: boolean;    // show pending badge
}

/** Resolve a lucide icon name string to the component, fallback to Puzzle */
function resolveIcon(name: string): React.ElementType {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const icons = LucideIcons as unknown as Record<string, React.ElementType>;
  return icons[name] ?? Puzzle;
}

export function Sidebar() {
  const [isOpen, setIsOpen] = useState(false);
  const [isRestarting, setIsRestarting] = useState(false);
  const [pendingContent, setPendingContent] = useState(0);
  const [pluginItems, setPluginItems] = useState<PluginNavItem[]>([]);
  const [version, setVersion] = useState<string>('');
  const pathname = usePathname();
  const isOnline = useChatStore((state) => state.wsConnected);
  const token = useAuthStore((s) => s.token);

  // Load plugin nav items + version once on mount
  useEffect(() => {
    const fetchPluginNav = async () => {
      try {
        const res = await fetch('/api/plugins/nav', {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (res.ok) {
          const data: PluginNavItem[] = await res.json();
          setPluginItems(data);
        }
      } catch { /* ignore — plugins are optional */ }
    };
    const fetchVersion = async () => {
      try {
        const res = await fetch('/api/system/info');
        if (res.ok) {
          const data = await res.json();
          if (data.version) setVersion(`v${data.version}`);
        }
      } catch { /* ignore */ }
    };
    if (token) fetchPluginNav();
    fetchVersion();
  }, [token]);

  // Poll for pending content count (from plugins that register a badge)
  useEffect(() => {
    const fetchPending = async () => {
      try {
        const res = await fetch('/api/content/pending-count', {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (res.ok) {
          const data = await res.json();
          setPendingContent(data.count ?? 0);
        }
      } catch { /* ignore */ }
    };
    fetchPending();
    const interval = setInterval(fetchPending, 30_000);
    return () => clearInterval(interval);
  }, [token]);

  const handleRestart = async () => {
    if (isRestarting) return;
    setIsRestarting(true);
    try {
      await fetch('/api/system/restart', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
    } catch { /* server closes connection before responding */ }
    const poll = async () => {
      for (let i = 0; i < 60; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        try {
          const res = await fetch('/api/ping');
          if (res.ok) { window.location.reload(); return; }
        } catch { /* still down */ }
      }
      window.location.reload();
    };
    poll();
  };

  const renderNavItem = (
    href: string,
    label: string,
    Icon: React.ElementType,
    badge?: number,
  ) => {
    const isActive = pathname === href || pathname.startsWith(href + '/');
    return (
      <li key={href}>
        <Link
          href={href}
          onClick={() => setIsOpen(false)}
          className={cn(
            "flex items-center gap-3 px-[11px] py-[9px] rounded-[6px] text-[13px] transition-all duration-[140ms]",
            isActive
              ? "acm-active-pill font-semibold"
              : "font-medium text-[var(--acm-fg-2)] nav-inactive"
          )}
        >
          <Icon size={16} strokeWidth={isActive ? 2.2 : 1.8} />
          <span className="flex-1">{label}</span>
          {badge !== undefined && badge > 0 && (
            <span className="mono text-[10px] font-bold bg-[var(--acm-accent)] text-[oklch(0.18_0.015_80)] rounded-full px-[5px] py-[1px] min-w-[18px] text-center leading-none">
              {badge > 99 ? '99+' : badge}
            </span>
          )}
        </Link>
      </li>
    );
  };

  const workspaceItems = coreNavItems.filter(i => !['/debug', '/config'].includes(i.href));
  const systemItems = coreNavItems.filter(i => ['/debug', '/config'].includes(i.href));
  const mainPluginItems = pluginItems.filter((p) => !p.section || p.section === 'main');
  const bottomPluginItems = pluginItems.filter((p) => p.section === 'bottom');

  return (
    <>
      {/* Mobile menu button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="lg:hidden fixed top-4 left-4 z-50 p-2 bg-[var(--acm-card)] border border-[var(--acm-border)] rounded-[6px] text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)] transition-colors"
      >
        {isOpen ? <X size={24} /> : <Menu size={24} />}
      </button>

      {/* Sidebar */}
      <nav className={cn(
        "dot-grid fixed left-0 top-0 h-screen w-64 border-r flex flex-col z-40 transition-transform duration-300 ease-in-out",
        "bg-[var(--acm-base)] border-[var(--acm-border)]",
        isOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
      )}>
        {/* Header */}
        <div className="min-h-[68px] px-5 py-[16px] border-b border-[var(--acm-border)] flex items-center gap-3">
          <div className="w-10 h-10 border border-[var(--acm-border-strong)] rounded-[8px] flex items-center justify-center text-[var(--acm-accent)] flex-shrink-0">
            <ACMMark size={24} />
          </div>
          <div className="flex flex-col leading-[1.2] min-w-0">
            <span className="text-[14px] font-semibold text-[var(--acm-fg)]">OpenACM</span>
            <span className="mono text-[9px] text-[var(--acm-fg-4)] tracking-wide">Autonomous · Open · Yours</span>
          </div>
        </div>

        {/* Navigation */}
        <ul className="flex-1 py-2 px-2 overflow-y-auto acm-scroll">
          {/* Workspace section */}
          <li>
            <span className="label px-[10px] py-[6px] block">Workspace</span>
          </li>
          {workspaceItems.map((item) =>
            renderNavItem(item.href, item.label, item.icon)
          )}

          {/* System section */}
          <li>
            <span className="label px-[10px] py-[6px] block pt-3">System</span>
          </li>
          {systemItems.map((item) =>
            renderNavItem(item.href, item.label, item.icon)
          )}

          {/* Plugin items (main section) */}
          {mainPluginItems.length > 0 && (
            <>
              <li>
                <span className="label px-[10px] py-[6px] block pt-3">Plugins</span>
              </li>
              {mainPluginItems.map((item) => {
                const Icon = resolveIcon(item.icon);
                const badge = item.badge ? pendingContent : undefined;
                return renderNavItem(item.path, item.label, Icon, badge);
              })}
            </>
          )}

          {/* Bottom-section plugin items */}
          {bottomPluginItems.map((item) => {
            const Icon = resolveIcon(item.icon);
            const badge = item.badge ? pendingContent : undefined;
            return renderNavItem(item.path, item.label, Icon, badge);
          })}
        </ul>

        {/* Footer */}
        <div className="border-t border-[var(--acm-border)] p-[14px] space-y-[10px]">
          {/* Mini tamagotchi */}
          <div className="flex items-center justify-center">
            <TamagotchiWidget size={44} />
          </div>

          {/* Agent status card */}
          <div className="flex items-center gap-[10px] px-[10px] py-[8px] border border-[var(--acm-border)] rounded-[6px] bg-[var(--acm-card)]">
            <span className={cn("dot", isOnline ? "dot-ok acm-pulse" : "dot-warn")} />
            <div className="flex-1 leading-[1.2] min-w-0">
              <span className="block text-[11.5px] text-[var(--acm-fg-2)]">
                {isOnline ? 'Agent online' : 'Connecting...'}
              </span>
              <span className="mono block text-[10px] text-[var(--acm-fg-4)]">
                {version || 'v0.1.0'}
              </span>
            </div>
            <SignalStripe active={isOnline ? 3 : 1} total={4} />
          </div>

          {/* Restart button */}
          <button
            onClick={handleRestart}
            disabled={isRestarting}
            className="w-full flex items-center justify-center gap-2 py-[7px] rounded-[6px] text-[12px] text-[var(--acm-fg-3)] border border-[var(--acm-border)] hover:border-[var(--acm-err)] hover:text-[var(--acm-err)] transition-colors duration-[140ms] disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isRestarting
              ? <><Loader2 size={13} className="animate-spin" /> Restarting...</>
              : <><RotateCcw size={13} /> Restart OpenACM</>
            }
          </button>
        </div>
      </nav>

      {/* Overlay for mobile */}
      {isOpen && (
        <div
          className="lg:hidden fixed inset-0 bg-black/50 z-30"
          onClick={() => setIsOpen(false)}
        />
      )}
    </>
  );
}
