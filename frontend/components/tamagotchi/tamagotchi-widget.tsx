'use client';

import { useEffect, useState, useRef } from 'react';
import dynamic from 'next/dynamic';
import { useTamagotchiStore, AgentState } from '@/stores/tamagotchi-store';

const Lottie = dynamic(() => import('lottie-react'), { ssr: false });

const LOOPING_STATES: AgentState[] = ['idle', 'thinking', 'working'];

const STATE_LABELS: Record<AgentState, string> = {
  idle: 'IDLE',
  thinking: 'THINKING',
  working: 'WORKING',
  success: 'SUCCESS',
  error: 'ERROR',
};

const STATE_COLORS: Record<AgentState, string> = {
  idle: 'text-blue-400',
  thinking: 'text-purple-400',
  working: 'text-orange-400',
  success: 'text-green-400',
  error: 'text-red-400',
};

interface TamagotchiWidgetProps {
  size?: number;
  showLabel?: boolean;
}

export function TamagotchiWidget({ size = 120, showLabel = false }: TamagotchiWidgetProps) {
  const { agentState, activeSkin, setAgentState } = useTamagotchiStore();
  // Keep previous animData visible while next one loads — no flash of CSS fallback
  const [animData, setAnimData] = useState<object | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const candidates = activeSkin !== 'default_robot'
      ? [activeSkin, 'default_robot']
      : ['default_robot'];

    (async () => {
      for (const skin of candidates) {
        try {
          const res = await fetch(`/static/skins/${skin}/${agentState}.json`, {
            signal: controller.signal,
          });
          if (res.ok) {
            const data = await res.json();
            if (!controller.signal.aborted) setAnimData(data);
            return;
          }
        } catch {
          if (controller.signal.aborted) return;
        }
      }
      // All failed — only clear if nothing was loaded yet (keep previous on error)
      if (!controller.signal.aborted) setAnimData((prev) => prev);
    })();

    return () => controller.abort();
  }, [agentState, activeSkin]);

  const isLooping = LOOPING_STATES.includes(agentState);
  // Keep a ref so the onComplete callback never has a stale isLooping value
  const isLoopingRef = useRef(isLooping);
  isLoopingRef.current = isLooping;

  return (
    <div className="flex flex-col items-center">
      {animData ? (
        <Lottie
          animationData={animData}
          loop={isLooping}
          autoplay
          style={{ width: size, height: size }}
          onComplete={() => { if (!isLoopingRef.current) setAgentState('idle'); }}
        />
      ) : (
        <CSSFallback state={agentState} size={size} />
      )}

      {showLabel && (
        <span className={`text-[10px] font-bold tracking-widest mt-1 ${STATE_COLORS[agentState]}`}>
          {STATE_LABELS[agentState]}
        </span>
      )}
    </div>
  );
}

// ── CSS fallback ──────────────────────────────────────────────────────────────

const CSS_CONFIGS: Record<AgentState, { bg: string; ring?: string; anim: string }> = {
  idle:     { bg: 'bg-blue-500',   ring: 'border-blue-400/30',   anim: 'animate-pulse'  },
  thinking: { bg: 'bg-purple-500', ring: 'border-purple-400/50', anim: 'animate-spin'   },
  working:  { bg: 'bg-orange-500', ring: 'border-orange-400/30', anim: 'animate-bounce' },
  success:  { bg: 'bg-green-500',                                anim: 'animate-ping'   },
  error:    { bg: 'bg-red-500',                                  anim: 'animate-pulse'  },
};

function CSSFallback({ state, size }: { state: AgentState; size: number }) {
  const cfg = CSS_CONFIGS[state];
  return (
    <div className="relative flex items-center justify-center" style={{ width: size, height: size }}>
      {cfg.ring && (
        <span
          className={`absolute rounded-full border-2 ${cfg.ring}`}
          style={{ width: size * 0.65, height: size * 0.65 }}
        />
      )}
      <span
        className={`rounded-full ${cfg.bg} ${cfg.anim}`}
        style={{ width: size * 0.45, height: size * 0.45 }}
      />
    </div>
  );
}
