'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
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
} from 'lucide-react';
import { useDashboardStore } from '@/stores/dashboard-store';
import { useChatStore } from '@/stores/chat-store';
import { useAuthStore } from '@/stores/auth-store';
import { translations } from '@/lib/translations';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const t = translations.navigation;

const navItems = [
  { href: '/dashboard', label: t.dashboard, icon: LayoutDashboard },
  { href: '/chat', label: t.chat, icon: MessageSquare },
  { href: '/tools', label: t.tools, icon: Wrench },
  { href: '/skills', label: t.skills, icon: Brain },
  { href: '/agents', label: t.agents, icon: Bot },
  { href: '/mcp', label: t.mcp, icon: Plug },
  { href: '/config', label: t.config, icon: Settings },
];

export function Sidebar() {
  const [isOpen, setIsOpen] = useState(false);
  const [isRestarting, setIsRestarting] = useState(false);
  const pathname = usePathname();
  const isOnline = useChatStore((state) => state.wsConnected);
  const token = useAuthStore((s) => s.token);

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
        <div className="p-6 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <span className="text-3xl">🧠</span>
            <div>
              <h1 className="text-xl font-bold text-white">OpenACM</h1>
              <span className="text-xs text-slate-500">v0.1.0</span>
            </div>
          </div>
        </div>
        
        {/* Navigation */}
        <ul className="flex-1 py-4 px-3 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
            
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  onClick={() => setIsOpen(false)}
                  className={cn(
                    "flex items-center gap-3 px-4 py-3 rounded-lg transition-all duration-200",
                    isActive 
                      ? "bg-blue-600/20 text-blue-400 border border-blue-600/30" 
                      : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                  )}
                >
                  <Icon size={20} />
                  <span className="font-medium">{item.label}</span>
                </Link>
              </li>
            );
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
