'use client';

import { useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { TamagotchiWidget } from '@/components/tamagotchi/tamagotchi-widget';
import { useTamagotchiStore, AgentState } from '@/stores/tamagotchi-store';
import { useChatStore } from '@/stores/chat-store';
import { Heart, Folder, Info, ChevronRight } from 'lucide-react';

// ── Built-in skins (add entries here when you bundle more skins) ──────────────
const AVAILABLE_SKINS = [
  {
    id: 'space_cat',
    name: 'Space Cat',
    description: 'Michilactic — un gatito astronauta en su cohete.',
    preview: '🐱',
  },
  // Drop your skin folder under public/skins/ and add an entry here:
  // { id: 'hacker_cat', name: 'Hacker Cat', description: '...', preview: '🐱' },
];

const STATE_INFO: Record<AgentState, { label: string; color: string; bg: string; desc: string }> = {
  idle: {
    label: 'IDLE',
    color: 'text-blue-400',
    bg: 'bg-blue-500/10 border-blue-500/20',
    desc: 'Waiting for your command.',
  },
  thinking: {
    label: 'THINKING',
    color: 'text-purple-400',
    bg: 'bg-purple-500/10 border-purple-500/20',
    desc: 'Analyzing context and generating a response.',
  },
  working: {
    label: 'WORKING',
    color: 'text-orange-400',
    bg: 'bg-orange-500/10 border-orange-500/20',
    desc: 'Executing tools, running code, or operating the system.',
  },
  success: {
    label: 'SUCCESS',
    color: 'text-green-400',
    bg: 'bg-green-500/10 border-green-500/20',
    desc: 'Task completed successfully.',
  },
  error: {
    label: 'ERROR',
    color: 'text-red-400',
    bg: 'bg-red-500/10 border-red-500/20',
    desc: 'Something went wrong. Check the terminal.',
  },
};

export default function TamagotchiPage() {
  const { agentState, activeSkin, setActiveSkin } = useTamagotchiStore();
  const thinkingLabel = useChatStore((s) => s.thinkingLabel);
  const isWaiting = useChatStore((s) => s.isWaitingResponse);
  const [showGuide, setShowGuide] = useState(false);

  const info = STATE_INFO[agentState];

  return (
    <AppLayout>
      <div className="p-6 lg:p-8 max-w-4xl mx-auto">
        {/* Header */}
        <header className="mb-8">
          <div className="flex items-center gap-3">
            <Heart size={28} className="text-pink-400" />
            <div>
              <h1 className="text-3xl font-bold text-white">Tamagotchi</h1>
              <p className="text-slate-400 mt-1 text-sm">Your AI agent, alive.</p>
            </div>
          </div>
        </header>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* ── Main display ── */}
          <div className="lg:col-span-2 flex flex-col gap-4">

            {/* Animation panel */}
            <div className="bg-slate-900 rounded-2xl border border-slate-800 p-8 flex flex-col items-center">
              <TamagotchiWidget size={200} />

              {/* State badge */}
              <div className={`mt-6 flex items-center gap-2 px-4 py-2 rounded-full border ${info.bg}`}>
                <span className={`w-2 h-2 rounded-full ${
                  agentState === 'idle' ? 'bg-blue-400' :
                  agentState === 'thinking' ? 'bg-purple-400 animate-pulse' :
                  agentState === 'working' ? 'bg-orange-400 animate-pulse' :
                  agentState === 'success' ? 'bg-green-400' : 'bg-red-400'
                }`} />
                <span className={`text-sm font-bold tracking-widest ${info.color}`}>
                  {info.label}
                </span>
              </div>

              {/* Sub-label */}
              <p className="mt-3 text-sm text-slate-500 text-center min-h-[20px]">
                {isWaiting && thinkingLabel ? thinkingLabel : info.desc}
              </p>
            </div>

            {/* All states grid */}
            <div className="bg-slate-900 rounded-xl border border-slate-800 p-5">
              <p className="text-xs text-slate-500 font-semibold uppercase tracking-widest mb-3">
                State Contract
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {(Object.entries(STATE_INFO) as [AgentState, typeof info][]).map(([key, s]) => (
                  <div
                    key={key}
                    className={`flex items-start gap-3 p-3 rounded-lg border ${
                      agentState === key ? s.bg : 'border-transparent'
                    }`}
                  >
                    <span className={`text-xs font-bold tracking-wider mt-0.5 w-16 shrink-0 ${s.color}`}>
                      {s.label}
                    </span>
                    <span className="text-xs text-slate-400">{s.desc}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* ── Right column ── */}
          <div className="flex flex-col gap-4">

            {/* Skin selector */}
            <div className="bg-slate-900 rounded-xl border border-slate-800 p-5">
              <p className="text-xs text-slate-500 font-semibold uppercase tracking-widest mb-3">
                Active Skin
              </p>
              <div className="space-y-2">
                {AVAILABLE_SKINS.map((skin) => (
                  <button
                    key={skin.id}
                    onClick={() => setActiveSkin(skin.id)}
                    className={`w-full flex items-center gap-3 px-3 py-3 rounded-lg border transition-all ${
                      activeSkin === skin.id
                        ? 'bg-blue-600/20 border-blue-600/40 text-blue-300'
                        : 'border-slate-800 hover:border-slate-600 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <span className="text-2xl">{skin.preview}</span>
                    <div className="text-left">
                      <p className="text-sm font-medium leading-none">{skin.name}</p>
                      <p className="text-[11px] text-slate-500 mt-1">{skin.description}</p>
                    </div>
                    {activeSkin === skin.id && (
                      <span className="ml-auto text-xs bg-blue-600 text-white rounded-full px-2 py-0.5">
                        Active
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>

            {/* How to add skins */}
            <div className="bg-slate-900 rounded-xl border border-slate-800 p-5">
              <button
                onClick={() => setShowGuide((v) => !v)}
                className="w-full flex items-center justify-between text-left"
              >
                <div className="flex items-center gap-2">
                  <Folder size={14} className="text-slate-500" />
                  <span className="text-xs text-slate-500 font-semibold uppercase tracking-widest">
                    Add Custom Skin
                  </span>
                </div>
                <ChevronRight
                  size={14}
                  className={`text-slate-600 transition-transform ${showGuide ? 'rotate-90' : ''}`}
                />
              </button>

              {showGuide && (
                <div className="mt-4 space-y-3">
                  <div className="flex items-start gap-2 text-xs text-slate-400">
                    <Info size={12} className="text-slate-600 mt-0.5 shrink-0" />
                    <span>Each skin is a folder under <code className="text-slate-300 bg-slate-800 px-1 rounded">public/skins/</code> with 5 Lottie JSON files.</span>
                  </div>

                  <div className="bg-slate-800/50 rounded-lg p-3 font-mono text-xs text-slate-300 space-y-0.5">
                    <p className="text-slate-500">public/skins/</p>
                    <p className="text-slate-500">└── <span className="text-amber-400">your_skin_name</span>/</p>
                    <p className="pl-4 text-green-400">├── idle.json</p>
                    <p className="pl-4 text-purple-400">├── thinking.json</p>
                    <p className="pl-4 text-orange-400">├── working.json</p>
                    <p className="pl-4 text-emerald-400">├── success.json</p>
                    <p className="pl-4 text-red-400">└── error.json</p>
                  </div>

                  <p className="text-xs text-slate-500">
                    Then add your skin to <code className="text-slate-300 bg-slate-800 px-1 rounded">AVAILABLE_SKINS</code> in <code className="text-slate-300 bg-slate-800 px-1 rounded">app/tamagotchi/page.tsx</code>.
                  </p>
                  <p className="text-xs text-slate-500">
                    Missing files automatically fall back to <code className="text-slate-300 bg-slate-800 px-1 rounded">default_robot</code>.
                    Free Lottie animations: <span className="text-blue-400">lottiefiles.com</span>
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
