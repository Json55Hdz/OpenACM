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
import { translations } from '@/lib/translations';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

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
  const pathname = usePathname();
  const isOnline = useChatStore((state) => state.wsConnected);
  const token = useAuthStore((s) => s.token);

  // Load plugin nav items once on mount
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
    if (token) fetchPluginNav();
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
            "flex items-center gap-3 px-4 py-3 rounded-lg transition-all duration-200",
            isActive
              ? "bg-blue-600/20 text-blue-400 border border-blue-600/30"
              : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
          )}
        >
          <Icon size={20} />
          <span className="font-medium flex-1">{label}</span>
          {badge !== undefined && badge > 0 && (
            <span className="ml-auto text-xs font-bold bg-amber-500 text-black rounded-full px-1.5 py-0.5 min-w-[20px] text-center leading-tight">
              {badge > 99 ? '99+' : badge}
            </span>
          )}
        </Link>
      </li>
    );
  };

  const mainPluginItems = pluginItems.filter((p) => !p.section || p.section === 'main');
  const bottomPluginItems = pluginItems.filter((p) => p.section === 'bottom');

  return (
    <>
      {/* Mobile menu button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="lg:hidden fixed top-4 left-4 z-50 p-2 bg-slate-800 rounded-lg text-slate-300 hover:text-white transition-colors"
      >
        {isOpen ? <X size={24} /> : <Menu size={24} />}
      </button>

      {/* Sidebar */}
      <nav className={cn(
        "fixed left-0 top-0 h-screen w-64 bg-slate-900 border-r border-slate-800 flex flex-col z-40 transition-transform duration-300 ease-in-out",
        isOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
      )}>
        {/* Header */}
        <div className="py-5 px-3 border-b border-slate-800 flex flex-col items-center">
          <img src="/static/logo-transparent.png" alt="OpenACM" width={110} height={110} className="rounded-xl" />
          <span className="text-xs text-slate-500 mt-1">v0.1.0</span>
        </div>

        {/* Navigation */}
        <ul className="flex-1 py-4 px-3 space-y-1 overflow-y-auto">
          {/* Core items */}
          {coreNavItems.map((item) =>
            renderNavItem(item.href, item.label, item.icon)
          )}

          {/* Plugin items (main section) */}
          {mainPluginItems.length > 0 && (
            <>
              <li className="pt-2 pb-1">
                <span className="px-4 text-[10px] font-semibold uppercase tracking-widest text-slate-600">
                  Plugins
                </span>
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
        <div className="p-4 border-t border-slate-800 space-y-2">
          <div className="flex items-center gap-2 px-4 py-2">
            <span className={cn(
              "w-2 h-2 rounded-full",
              isOnline ? "bg-green-500 animate-pulse" : "bg-yellow-500"
            )}></span>
            <span className="text-sm text-slate-400">
              {isOnline ? translations.dashboard.connected : translations.dashboard.connecting}
            </span>
          </div>
          <button
            onClick={handleRestart}
            disabled={isRestarting}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-xs font-medium bg-red-900/30 hover:bg-red-800/40 text-red-400 border border-red-700/30 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
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
