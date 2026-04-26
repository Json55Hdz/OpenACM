'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
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

type SegmentsManifest = Partial<Record<AgentState, [number, number]>> & {
  jump?: [number, number]; // optional idle variation
};

interface AnimState {
  data: object;
  segment: [number, number] | null;
  jumpSegment: [number, number] | null; // idle fidget, if skin supports it
}

// Module-level cache: animation.json is only downloaded once per skin per session
const _segmentedCache = new Map<string, { animData: object; segments: SegmentsManifest }>();

// Random delay between idle fidgets: 7–18 seconds
const nextJumpDelay = () => 7000 + Math.random() * 11000;

interface TamagotchiWidgetProps {
  size?: number;
  showLabel?: boolean;
}

export function TamagotchiWidget({ size = 120, showLabel = false }: TamagotchiWidgetProps) {
  const { agentState, activeSkin, setAgentState } = useTamagotchiStore();
  const [anim, setAnim] = useState<AnimState | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Idle fidget state — internal only, never touches the Zustand store
  const [jumping, setJumping] = useState(false);
  const [playKey, setPlayKey] = useState(0);
  const jumpTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Load animation data when state or skin changes ──────────────────────────
  useEffect(() => {
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const sig = controller.signal;

    const candidates = activeSkin !== 'space_cat'
      ? [activeSkin, 'space_cat']
      : ['space_cat'];

    (async () => {
      for (const skin of candidates) {
        // 1. Classic format: individual {state}.json per skin
        try {
          const res = await fetch(`/static/skins/${skin}/${agentState}.json`, { signal: sig });
          if (res.ok) {
            const data = await res.json();
            if (!sig.aborted) setAnim({ data, segment: null, jumpSegment: null });
            return;
          }
        } catch { if (sig.aborted) return; }

        // 2. Segmented format: animation.json + segments.json
        try {
          let cached = _segmentedCache.get(skin);
          if (!cached) {
            const segRes = await fetch(`/static/skins/${skin}/segments.json`, { signal: sig });
            if (segRes.ok) {
              const segments: SegmentsManifest = await segRes.json();
              const animRes = await fetch(`/static/skins/${skin}/animation.json`, { signal: sig });
              if (animRes.ok) {
                const animData = await animRes.json();
                cached = { animData, segments };
                _segmentedCache.set(skin, cached);
              }
            }
          }
          if (cached) {
            const seg = cached.segments[agentState] ?? null;
            const jumpSeg = cached.segments.jump ?? null;
            if ((seg || agentState === 'idle') && !sig.aborted) {
              setAnim({ data: cached.animData, segment: seg, jumpSegment: jumpSeg });
              return;
            }
          }
        } catch { if (sig.aborted) return; }
      }

      if (!sig.aborted) setAnim(prev => prev);
    })();

    return () => controller.abort();
  }, [agentState, activeSkin]);

  // ── Idle fidget scheduler ────────────────────────────────────────────────────
  const scheduleNextJump = useCallback(() => {
    if (jumpTimerRef.current) clearTimeout(jumpTimerRef.current);
    jumpTimerRef.current = setTimeout(() => {
      // Only fire if still idle (guard against stale closures)
      setJumping(true);
      setPlayKey(k => k + 1);
    }, nextJumpDelay());
  }, []);

  useEffect(() => {
    const hasJump = anim?.jumpSegment != null;
    if (agentState !== 'idle' || !hasJump) {
      if (jumpTimerRef.current) clearTimeout(jumpTimerRef.current);
      setJumping(false);
      return;
    }
    scheduleNextJump();
    return () => { if (jumpTimerRef.current) clearTimeout(jumpTimerRef.current); };
  }, [agentState, anim?.jumpSegment, scheduleNextJump]);

  const isLooping = LOOPING_STATES.includes(agentState);
  const isLoopingRef = useRef(isLooping);
  isLoopingRef.current = isLooping;

  const activeSegment = jumping && anim?.jumpSegment
    ? anim.jumpSegment
    : (anim?.segment ?? undefined);
  const activeLoop = jumping ? false : isLooping;

  const handleComplete = useCallback(() => {
    if (jumping) {
      // Jump finished — back to idle loop, then schedule the next one
      setJumping(false);
      setPlayKey(k => k + 1);
      scheduleNextJump();
    } else if (!isLoopingRef.current) {
      setAgentState('idle');
    }
  }, [jumping, scheduleNextJump, setAgentState]);

  return (
    <div className="flex flex-col items-center">
      {anim ? (
        <Lottie
          key={`${agentState}-${playKey}`}
          animationData={anim.data}
          loop={activeLoop}
          autoplay
          initialSegment={activeSegment}
          style={{ width: size, height: size }}
          onComplete={handleComplete}
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
