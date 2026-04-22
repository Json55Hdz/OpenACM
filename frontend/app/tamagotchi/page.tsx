'use client';

import { useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { TamagotchiWidget } from '@/components/tamagotchi/tamagotchi-widget';
import { ACMMark } from '@/components/ui/acm-mark';
import { useTamagotchiStore, AgentState } from '@/stores/tamagotchi-store';
import { useChatStore } from '@/stores/chat-store';
import { Folder, Info, ChevronRight } from 'lucide-react';

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

const STATE_INFO: Record<AgentState, { label: string; color: string; desc: string }> = {
  idle: {
    label: 'IDLE',
    color: 'var(--acm-info)',
    desc: 'Waiting for your command.',
  },
  thinking: {
    label: 'THINKING',
    color: 'oklch(0.72 0.15 300)',
    desc: 'Analyzing context and generating a response.',
  },
  working: {
    label: 'WORKING',
    color: 'var(--acm-accent)',
    desc: 'Executing tools, running code, or operating the system.',
  },
  success: {
    label: 'SUCCESS',
    color: 'var(--acm-ok)',
    desc: 'Task completed successfully.',
  },
  error: {
    label: 'ERROR',
    color: 'var(--acm-err)',
    desc: 'Something went wrong. Check the terminal.',
  },
};

// Dot class per state
function stateDotClass(state: AgentState): string {
  if (state === 'idle')    return 'dot dot-idle';
  if (state === 'success') return 'dot dot-ok';
  if (state === 'error')   return 'dot dot-err';
  return 'dot dot-accent'; // thinking / working
}

export default function TamagotchiPage() {
  const { agentState, activeSkin, setActiveSkin } = useTamagotchiStore();
  const thinkingLabel = useChatStore((s) => s.thinkingLabel);
  const isWaiting = useChatStore((s) => s.isWaitingResponse);
  const [showGuide, setShowGuide] = useState(false);

  const info = STATE_INFO[agentState];
  const isPulsing = agentState === 'thinking' || agentState === 'working';

  return (
    <AppLayout>
      <div className="p-6 lg:p-8 max-w-4xl mx-auto">

        {/* ── Header ── */}
        <header className="mb-8">
          <span className="acm-breadcrumb">ACM / Tamagotchi</span>
          <h1 className="text-2xl font-semibold" style={{ color: 'var(--acm-fg)' }}>
            Tamagotchi
          </h1>
          <p className="text-sm mt-1" style={{ color: 'var(--acm-fg-3)' }}>
            Your AI agent, alive.
          </p>
        </header>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

          {/* ── Left: main display ── */}
          <div className="lg:col-span-2 flex flex-col gap-4">

            {/* CRT display panel */}
            <div
              className="acm-card flex flex-col items-center p-8 relative overflow-hidden"
              style={{
                background: 'radial-gradient(ellipse at 50% 30%, oklch(0.22 0.01 255) 0%, oklch(0.14 0.006 255) 100%)',
                border: '1px solid var(--acm-border-strong)',
              }}
            >
              {/* Corner tick marks */}
              <span style={{ position: 'absolute', top: 10, left: 10, width: 8, height: 8, borderTop: '1px solid var(--acm-border-strong)', borderLeft: '1px solid var(--acm-border-strong)' }} />
              <span style={{ position: 'absolute', top: 10, right: 10, width: 8, height: 8, borderTop: '1px solid var(--acm-border-strong)', borderRight: '1px solid var(--acm-border-strong)' }} />
              <span style={{ position: 'absolute', bottom: 10, left: 10, width: 8, height: 8, borderBottom: '1px solid var(--acm-border-strong)', borderLeft: '1px solid var(--acm-border-strong)' }} />
              <span style={{ position: 'absolute', bottom: 10, right: 10, width: 8, height: 8, borderBottom: '1px solid var(--acm-border-strong)', borderRight: '1px solid var(--acm-border-strong)' }} />

              {/* ACMMark logo — amber with drop-shadow */}
              <div
                style={{
                  filter: 'drop-shadow(0 0 18px oklch(0.84 0.16 82 / 0.55))',
                  marginBottom: '1rem',
                }}
              >
                <ACMMark size={120} color="var(--acm-accent)" />
              </div>

              {/* Tamagotchi widget */}
              <TamagotchiWidget size={200} />

              {/* State badge pill */}
              <div
                className="mt-6 flex items-center gap-2 px-4 py-2 rounded-full"
                style={{
                  background: `${info.color}18`,
                  border: `1px solid ${info.color}33`,
                }}
              >
                <span
                  className={`${stateDotClass(agentState)}${isPulsing ? ' acm-pulse' : ''}`}
                  style={agentState === 'thinking' ? { background: 'oklch(0.72 0.15 300)', boxShadow: '0 0 6px oklch(0.72 0.15 300 / 0.6)' } : undefined}
                />
                <span
                  className="text-sm font-bold tracking-widest mono"
                  style={{ color: info.color }}
                >
                  {info.label}
                </span>
              </div>

              {/* Sub-label */}
              <p
                className="mt-3 text-sm text-center min-h-[20px]"
                style={{ color: 'var(--acm-fg-3)' }}
              >
                {isWaiting && thinkingLabel ? thinkingLabel : info.desc}
              </p>
            </div>

            {/* State contract card */}
            <div className="acm-card p-5">
              <p className="label mb-3">State Contract</p>
              <div className="flex flex-col gap-1">
                {(Object.entries(STATE_INFO) as [AgentState, typeof info][]).map(([key, s]) => {
                  const isActive = agentState === key;
                  return (
                    <div
                      key={key}
                      className="flex items-start gap-3 px-3 py-2 rounded-lg transition-all"
                      style={
                        isActive
                          ? {
                              background: 'var(--acm-elev)',
                              border: '1px solid var(--acm-border)',
                            }
                          : {
                              border: '1px solid transparent',
                            }
                      }
                    >
                      <span
                        className={`dot mt-1 shrink-0${isActive && (key === 'thinking' || key === 'working') ? ' acm-pulse' : ''}`}
                        style={{
                          background: s.color,
                          boxShadow: isActive ? `0 0 6px ${s.color}99` : undefined,
                        }}
                      />
                      <span
                        className="mono text-xs font-bold tracking-wider w-16 shrink-0 mt-0.5"
                        style={{ color: isActive ? s.color : 'var(--acm-fg-4)' }}
                      >
                        {s.label}
                      </span>
                      <span className="text-xs" style={{ color: 'var(--acm-fg-3)' }}>
                        {s.desc}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* ── Right column ── */}
          <div className="flex flex-col gap-4">

            {/* Skin selector */}
            <div className="acm-card p-5">
              <p className="label mb-3">Skins</p>
              <div className="flex flex-col gap-2">
                {AVAILABLE_SKINS.map((skin) => {
                  const isActive = activeSkin === skin.id;
                  return (
                    <button
                      key={skin.id}
                      onClick={() => setActiveSkin(skin.id)}
                      className="w-full flex items-center gap-3 px-3 py-3 rounded-lg text-left transition-all"
                      style={
                        isActive
                          ? {
                              background: 'var(--acm-accent-soft)',
                              border: '1px solid var(--acm-accent-soft-strong, oklch(0.84 0.16 82 / 0.25))',
                            }
                          : {
                              background: 'transparent',
                              border: '1px solid var(--acm-border)',
                            }
                      }
                    >
                      {/* Stripe preview box */}
                      <span
                        className="text-xl shrink-0 flex items-center justify-center rounded"
                        style={{
                          width: 36,
                          height: 36,
                          background: isActive
                            ? 'var(--acm-accent-tint)'
                            : 'var(--acm-elev)',
                          border: isActive
                            ? '1px solid oklch(0.84 0.16 82 / 0.3)'
                            : '1px solid var(--acm-border)',
                          fontSize: 20,
                        }}
                      >
                        {skin.preview}
                      </span>

                      <div className="flex-1 min-w-0">
                        <p
                          className="text-sm font-medium leading-none truncate"
                          style={{ color: isActive ? 'var(--acm-accent)' : 'var(--acm-fg)' }}
                        >
                          {skin.name}
                        </p>
                        <p
                          className="text-[11px] mt-1 truncate"
                          style={{ color: 'var(--acm-fg-4)' }}
                        >
                          {skin.description}
                        </p>
                      </div>

                      {isActive && (
                        <span
                          className="mono text-[10px] font-bold shrink-0 px-2 py-0.5 rounded-full"
                          style={{
                            background: 'var(--acm-accent)',
                            color: 'oklch(0.18 0.015 80)',
                          }}
                        >
                          ON
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Add Custom Skin guide */}
            <div className="acm-card p-5">
              <button
                onClick={() => setShowGuide((v) => !v)}
                className="w-full flex items-center justify-between text-left"
              >
                <div className="flex items-center gap-2">
                  <Folder size={14} style={{ color: 'var(--acm-fg-4)' }} />
                  <span className="label">Add Custom Skin</span>
                </div>
                <ChevronRight
                  size={14}
                  style={{ color: 'var(--acm-fg-4)', transition: 'transform 160ms ease', transform: showGuide ? 'rotate(90deg)' : 'rotate(0deg)' }}
                />
              </button>

              {showGuide && (
                <div className="mt-4 space-y-3">
                  <div className="flex items-start gap-2 text-xs" style={{ color: 'var(--acm-fg-3)' }}>
                    <Info size={12} style={{ color: 'var(--acm-fg-4)', marginTop: 2, flexShrink: 0 }} />
                    <span>
                      Each skin is a folder under{' '}
                      <code
                        className="mono rounded px-1"
                        style={{ background: 'var(--acm-elev)', color: 'var(--acm-fg-2)', fontSize: 11 }}
                      >
                        public/skins/
                      </code>{' '}
                      with 5 Lottie JSON files.
                    </span>
                  </div>

                  {/* File tree */}
                  <div
                    className="mono rounded-lg p-3 text-xs space-y-0.5"
                    style={{ background: 'var(--acm-elev)', color: 'var(--acm-fg-3)' }}
                  >
                    <p style={{ color: 'var(--acm-fg-4)' }}>public/skins/</p>
                    <p style={{ color: 'var(--acm-fg-4)' }}>
                      └── <span style={{ color: 'var(--acm-accent)' }}>your_skin_name</span>/
                    </p>
                    <p className="pl-4" style={{ color: 'var(--acm-info)' }}>├── idle.json</p>
                    <p className="pl-4" style={{ color: 'oklch(0.72 0.15 300)' }}>├── thinking.json</p>
                    <p className="pl-4" style={{ color: 'var(--acm-accent)' }}>├── working.json</p>
                    <p className="pl-4" style={{ color: 'var(--acm-ok)' }}>├── success.json</p>
                    <p className="pl-4" style={{ color: 'var(--acm-err)' }}>└── error.json</p>
                  </div>

                  <p className="text-xs" style={{ color: 'var(--acm-fg-4)' }}>
                    Then add your skin to{' '}
                    <code
                      className="mono rounded px-1"
                      style={{ background: 'var(--acm-elev)', color: 'var(--acm-fg-2)', fontSize: 11 }}
                    >
                      AVAILABLE_SKINS
                    </code>{' '}
                    in{' '}
                    <code
                      className="mono rounded px-1"
                      style={{ background: 'var(--acm-elev)', color: 'var(--acm-fg-2)', fontSize: 11 }}
                    >
                      app/tamagotchi/page.tsx
                    </code>
                    .
                  </p>
                  <p className="text-xs" style={{ color: 'var(--acm-fg-4)' }}>
                    Missing files automatically fall back to{' '}
                    <code
                      className="mono rounded px-1"
                      style={{ background: 'var(--acm-elev)', color: 'var(--acm-fg-2)', fontSize: 11 }}
                    >
                      default_robot
                    </code>
                    .{' '}
                    Free Lottie animations:{' '}
                    <span style={{ color: 'var(--acm-accent)' }}>lottiefiles.com</span>
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
