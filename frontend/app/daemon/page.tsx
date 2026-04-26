'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { TamaPlaceholder } from '@/components/tamagotchi/global-tamagotchi';
import { ACMMark } from '@/components/ui/acm-mark';
import { useTamagotchiStore, AgentState } from '@/stores/tamagotchi-store';
import { useChatStore } from '@/stores/chat-store';
import { Folder, Info, ChevronRight, Mic, MicOff, Volume2, X, Zap, Radio, AlertTriangle, Server, Globe, Cpu, CheckCircle, Circle } from 'lucide-react';
import { VoiceState, VoiceEngineMode } from '@/hooks/use-voice-engine';
import { useVoice } from '@/components/providers/voice-provider';
import { useAPI } from '@/hooks/use-api';

const INTRO_STORAGE_KEY = 'openacm_voice_intro_seen';

// ── Built-in skins (add entries here when you bundle more skins) ──────────────
const AVAILABLE_SKINS = [
  {
    id: 'ai_robot',
    name: 'AI Robot',
    description: 'Roboto animado con 5 estados + fidget aleatorio en idle.',
    preview: '🤖',
  },
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

// ── Voice state metadata ───────────────────────────────────────────────────────
const VOICE_STATE_INFO: Record<VoiceState, { label: string; color: string; desc: string }> = {
  disabled:   { label: 'OFFLINE',     color: 'var(--acm-fg-4)',    desc: 'Voice interface disabled.' },
  passive:    { label: 'PASSIVE',     color: 'var(--acm-accent)',  desc: 'Listening for your wake word.' },
  activating: { label: 'WAKE WORD',  color: 'var(--acm-accent)',  desc: 'Wake word detected!' },
  listening:  { label: 'LISTENING',  color: 'oklch(0.74 0.06 230)', desc: 'Speak your command...' },
  processing: { label: 'PROCESSING', color: 'oklch(0.72 0.15 300)', desc: 'Thinking...' },
  speaking:   { label: 'SPEAKING',   color: 'var(--acm-ok)',       desc: 'Speaking response.' },
  error:      { label: 'ERROR',       color: 'var(--acm-err)',      desc: 'Mic permission denied or not supported.' },
};

// ── Voice Engine mode selector card ───────────────────────────────────────────
const ENGINE_MODES: { id: VoiceEngineMode; label: string; desc: string; icon: React.ElementType }[] = [
  { id: 'browser', label: 'Browser',  desc: 'Web Speech API + Kokoro JS (runs in browser tab)',  icon: Globe  },
  { id: 'server',  label: 'Server',   desc: 'Python mic + Whisper STT + pyttsx3 (runs on server)', icon: Server },
  { id: 'auto',    label: 'Auto',     desc: 'Prefer server if available, fall back to browser',    icon: Cpu    },
];

interface ServerTTSVoice { id: string; label: string; lang: string; gender: string; }

function VoiceEngineCard({
  engineMode,
  onSetMode,
  daemonStatus,
  onStartDaemon,
  onStopDaemon,
  onInstall,
  isInstalling,
  isStarting,
  installLog,
  micDevices,
  selectedMicId,
  onSetMic,
  serverTtsVoice,
  onSetServerTtsVoice,
  serverTtsVoices,
}: {
  engineMode: VoiceEngineMode;
  onSetMode: (m: VoiceEngineMode) => Promise<void>;
  daemonStatus: any;
  onStartDaemon: () => Promise<void>;
  onStopDaemon: () => Promise<void>;
  onInstall: () => Promise<void>;
  isInstalling: boolean;
  isStarting: boolean;
  installLog: string[];
  micDevices: any[];
  selectedMicId: string;
  onSetMic: (id: string) => void;
  serverTtsVoice: string;
  onSetServerTtsVoice: (id: string) => void;
  serverTtsVoices: ServerTTSVoice[];
}) {
  const logRef = useRef<HTMLDivElement>(null);
  const showDaemon = engineMode === 'server' || engineMode === 'auto';
  const daemonRunning = daemonStatus?.is_running ?? false;
  const daemonAvail = daemonStatus?.engine_available ?? false;
  const edgeTtsAvail = daemonStatus?.deps?.edge_tts ?? false;
  // Show INSTALL when core deps OR edge-tts are missing (edge-tts is optional but preferred)
  const needsInstall = !daemonAvail || !edgeTtsAvail;
  const isDaemonLoading = daemonStatus?.current_state === 'loading_model';

  // Auto-scroll install log to bottom
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [installLog]);

  return (
    <div className="acm-card p-5">
      <p className="label mb-3">Voice Engine</p>

      <div className="flex flex-col gap-2 mb-4">
        {ENGINE_MODES.map(({ id, label, desc, icon: Icon }) => {
          const active = engineMode === id;
          return (
            <button
              key={id}
              onClick={() => onSetMode(id)}
              className="w-full flex items-start gap-3 px-3 py-3 rounded-lg text-left transition-all"
              style={active
                ? { background: 'var(--acm-accent-soft)', border: '1px solid oklch(0.84 0.16 82 / 0.25)' }
                : { background: 'transparent', border: '1px solid var(--acm-border)' }
              }
            >
              <Icon size={14} style={{ color: active ? 'var(--acm-accent)' : 'var(--acm-fg-4)', marginTop: 2, flexShrink: 0 }} />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold" style={{ color: active ? 'var(--acm-accent)' : 'var(--acm-fg)' }}>{label}</p>
                <p className="text-[10px] mt-0.5 leading-snug" style={{ color: 'var(--acm-fg-4)' }}>{desc}</p>
              </div>
              {active && (
                <span className="mono text-[10px] font-bold shrink-0 px-1.5 py-0.5 rounded-full"
                  style={{ background: 'var(--acm-accent)', color: 'oklch(0.18 0.015 80)' }}>
                  ON
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Mic selector */}
      {micDevices.length > 0 && (
        <div className="mb-3">
          <p className="label mb-1.5" style={{ fontSize: 9 }}>Microphone</p>
          <select
            value={selectedMicId}
            onChange={e => onSetMic(e.target.value)}
            className="w-full text-xs rounded-lg px-2 py-1.5 mono"
            style={{
              background: 'var(--acm-elev)',
              border: '1px solid var(--acm-border)',
              color: 'var(--acm-fg-2)',
              outline: 'none',
            }}
          >
            {micDevices.map(d => (
              <option key={d.id} value={d.id}>
                {d.label}{d.isDefault ? ' ★' : ''}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Server TTS voice selector */}
      {showDaemon && serverTtsVoices.length > 0 && (
        <div className="mb-3">
          <p className="label mb-1.5" style={{ fontSize: 9 }}>Server voice (edge-tts)</p>
          <select
            value={serverTtsVoice}
            onChange={e => onSetServerTtsVoice(e.target.value)}
            className="w-full text-xs rounded-lg px-2 py-1.5 mono"
            style={{
              background: 'var(--acm-elev)',
              border: '1px solid var(--acm-border)',
              color: 'var(--acm-fg-2)',
              outline: 'none',
            }}
          >
            {serverTtsVoices.map(v => (
              <option key={v.id} value={v.id}>{v.label}</option>
            ))}
          </select>
        </div>
      )}

      {/* Server daemon controls */}
      {showDaemon && daemonStatus && (
        <div className="mt-1 pt-3" style={{ borderTop: '1px solid var(--acm-border)' }}>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className={`dot ${
                daemonRunning
                  ? isDaemonLoading ? 'dot-accent acm-pulse' : 'dot-ok acm-pulse'
                  : (isInstalling || isStarting) ? 'dot-accent acm-pulse' : 'dot-idle'
              }`} />
              <span className="text-xs font-medium" style={{ color: 'var(--acm-fg-2)' }}>
                {daemonRunning
                  ? isDaemonLoading
                    ? 'Cargando modelo Whisper…'
                    : daemonStatus?.current_state === 'passive'
                      ? 'Esperando wake word…'
                      : daemonStatus?.current_state === 'listening'
                        ? 'Escuchando — habla tu comando'
                        : daemonStatus?.current_state === 'processing'
                          ? 'Procesando…'
                          : daemonStatus?.current_state === 'speaking'
                            ? 'Respondiendo…'
                            : `Daemon · ${daemonStatus?.current_state}`
                  : isInstalling
                    ? (!daemonAvail ? 'Instalando dependencias…' : 'Instalando edge-tts…')
                    : isStarting
                      ? 'Iniciando daemon…'
                      : 'Server daemon · detenido'}
              </span>
            </div>
            {daemonRunning ? (
              <button
                onClick={onStopDaemon}
                className="text-[11px] mono font-bold px-3 py-1 rounded transition-all"
                style={{ background: 'oklch(0.68 0.13 22 / 0.15)', border: '1px solid oklch(0.68 0.13 22 / 0.4)', color: 'var(--acm-err)' }}
              >
                STOP
              </button>
            ) : needsInstall ? (
              <button
                onClick={onInstall}
                disabled={isInstalling}
                className="text-[11px] mono font-bold px-3 py-1 rounded transition-all"
                style={isInstalling
                  ? { background: 'var(--acm-elev)', border: '1px solid var(--acm-border)', color: 'var(--acm-fg-4)', cursor: 'not-allowed' }
                  : { background: 'oklch(0.74 0.06 230 / 0.12)', border: '1px solid oklch(0.74 0.06 230 / 0.35)', color: 'oklch(0.74 0.06 230)' }
                }
              >
                {isInstalling ? '…' : !daemonAvail ? 'INSTALL' : 'ADD VOICE'}
              </button>
            ) : (
              <button
                onClick={onStartDaemon}
                disabled={isStarting}
                className="text-[11px] mono font-bold px-3 py-1 rounded transition-all"
                style={isStarting
                  ? { background: 'var(--acm-elev)', border: '1px solid var(--acm-border)', color: 'var(--acm-fg-4)', cursor: 'not-allowed' }
                  : { background: 'var(--acm-accent-tint)', border: '1px solid oklch(0.84 0.16 82 / 0.3)', color: 'var(--acm-accent)' }
                }
              >
                {isStarting ? '…' : 'START'}
              </button>
            )}
          </div>

          {/* Dep status */}
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {Object.entries(daemonStatus.deps || {}).map(([dep, ok]) => (
              <span key={dep} className="flex items-center gap-1 text-[10px] mono" style={{ color: ok ? 'var(--acm-fg-3)' : 'var(--acm-fg-4)' }}>
                <span style={{ color: ok ? 'var(--acm-ok)' : 'var(--acm-fg-4)' }}>{ok ? '✓' : '○'}</span>
                {dep}
              </span>
            ))}
          </div>

          {/* Whisper model download indicator */}
          {isDaemonLoading && (
            <div className="mt-2 px-2 py-2 rounded flex items-start gap-2"
              style={{ background: 'oklch(0.84 0.16 82 / 0.07)', border: '1px solid oklch(0.84 0.16 82 / 0.2)' }}>
              <span className="dot dot-accent acm-pulse mt-0.5" style={{ flexShrink: 0 }} />
              <div>
                <p className="text-[11px] font-medium" style={{ color: 'var(--acm-fg-2)' }}>
                  Downloading Whisper base model (~150 MB)
                </p>
                <p className="text-[10px] mt-0.5" style={{ color: 'var(--acm-fg-4)' }}>
                  First-run download from HuggingFace. Will be cached — won't download again.
                </p>
              </div>
            </div>
          )}

          {/* Install log terminal */}
          {(isInstalling || installLog.length > 0) && (
            <div
              ref={logRef}
              className="mt-3 mono text-[10px] leading-relaxed overflow-y-auto"
              style={{
                maxHeight: 140,
                background: 'oklch(0.11 0.008 255)',
                border: '1px solid var(--acm-border)',
                borderRadius: 6,
                padding: '8px 10px',
                color: 'var(--acm-fg-3)',
              }}
            >
              {installLog.map((line, i) => (
                <div
                  key={i}
                  style={{
                    color: line.startsWith('✓') ? 'var(--acm-ok)'
                      : line.startsWith('✗') ? 'var(--acm-err)'
                      : 'var(--acm-fg-3)',
                  }}
                >
                  {line}
                </div>
              ))}
              {isInstalling && (
                <div style={{ color: 'var(--acm-accent)' }} className="acm-pulse">▌</div>
              )}
            </div>
          )}

          {daemonStatus.last_error && !isInstalling && !isStarting && (
            <div className="mt-2 px-2 py-1.5 rounded mono text-[10px] leading-snug"
              style={{ background: 'oklch(0.68 0.13 22 / 0.12)', border: '1px solid oklch(0.68 0.13 22 / 0.3)', color: 'var(--acm-err)' }}>
              {daemonStatus.last_error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Kokoro model download status card ─────────────────────────────────────────
function KokoroModelCard({ modelProgress, isModelReady }: { modelProgress: number | null; isModelReady: boolean }) {
  const isDownloading = modelProgress !== null;

  return (
    <div className="acm-card p-5">
      <div className="flex items-center justify-between mb-2">
        <p className="label">Kokoro Model</p>
        {isModelReady ? (
          <span className="flex items-center gap-1 text-[10px] mono font-bold" style={{ color: 'var(--acm-ok)' }}>
            <CheckCircle size={10} /> READY
          </span>
        ) : isDownloading ? (
          <span className="mono text-[10px] font-bold" style={{ color: 'var(--acm-accent)' }}>
            {modelProgress}%
          </span>
        ) : (
          <span className="flex items-center gap-1 text-[10px] mono" style={{ color: 'var(--acm-fg-4)' }}>
            <Circle size={10} /> NOT LOADED
          </span>
        )}
      </div>

      {isDownloading && (
        <div className="mb-3">
          <div style={{
            height: 4, borderRadius: 4,
            background: 'var(--acm-elev)',
            border: '1px solid var(--acm-border)',
            overflow: 'hidden',
          }}>
            <div style={{
              height: '100%',
              width: `${modelProgress}%`,
              background: 'var(--acm-accent)',
              borderRadius: 4,
              transition: 'width 0.3s ease',
            }} />
          </div>
          <p className="text-[10px] mt-1" style={{ color: 'var(--acm-fg-4)' }}>
            Downloading Kokoro-82M (~80 MB)…
          </p>
        </div>
      )}

      {!isDownloading && (
        <p className="text-[10px] leading-snug" style={{ color: 'var(--acm-fg-4)' }}>
          {isModelReady
            ? 'Kokoro neural TTS is cached and ready. No re-download needed.'
            : 'Kokoro (~80 MB) downloads on first use and caches in your browser.'}
        </p>
      )}
    </div>
  );
}

// ── Voice Aura — canvas-based orbital rings that react to audio ───────────────
function VoiceAura({
  voiceState,
  micAmplitude,
  speakerAmplitude,
}: {
  voiceState: VoiceState;
  micAmplitude: number;
  speakerAmplitude: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<number>(0);
  const phaseRef = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d')!;
    const W = canvas.width, H = canvas.height;
    const cx = W / 2, cy = H / 2;

    const draw = () => {
      ctx.clearRect(0, 0, W, H);
      phaseRef.current += 0.018;
      const phase = phaseRef.current;
      const amp = voiceState === 'speaking' ? speakerAmplitude : micAmplitude;

      if (voiceState === 'disabled') { animRef.current = requestAnimationFrame(draw); return; }

      // Accent color components
      const accentAlpha = voiceState === 'passive' ? 0.18 : 0.55;

      if (voiceState === 'passive') {
        // Single slow breathing ring
        const r = 120 + Math.sin(phase * 0.6) * 4;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.strokeStyle = `oklch(0.84 0.16 82 / ${accentAlpha})`;
        ctx.lineWidth = 1;
        ctx.stroke();
        // Tiny mic dot
        ctx.beginPath();
        ctx.arc(cx + r, cy, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = `oklch(0.84 0.16 82 / 0.5)`;
        ctx.fill();
      } else if (voiceState === 'activating') {
        // Flash: expanding rings
        for (let i = 0; i < 3; i++) {
          const r = 110 + i * 18 + Math.sin(phase * 4) * 6;
          ctx.beginPath();
          ctx.arc(cx, cy, r, 0, Math.PI * 2);
          ctx.strokeStyle = `oklch(0.84 0.16 82 / ${0.6 - i * 0.15})`;
          ctx.lineWidth = 2 - i * 0.4;
          ctx.stroke();
        }
      } else if (voiceState === 'listening') {
        // Waveform rings reacting to mic amplitude
        const rings = 4;
        for (let i = 0; i < rings; i++) {
          const base = 100 + i * 16;
          const pulse = amp * 30 * (1 - i * 0.2);
          const r = base + Math.sin(phase * 2 + i) * 3 + pulse;
          ctx.beginPath();
          ctx.arc(cx, cy, r, 0, Math.PI * 2);
          ctx.strokeStyle = `oklch(0.74 0.06 230 / ${(0.7 - i * 0.12) * (0.4 + amp)})`;
          ctx.lineWidth = 1.5 - i * 0.25;
          ctx.stroke();
        }
        // Amplitude spike dots at 8 positions
        for (let d = 0; d < 8; d++) {
          const angle = (d / 8) * Math.PI * 2 + phase;
          const r = 98 + amp * 35;
          const x = cx + Math.cos(angle) * r;
          const y = cy + Math.sin(angle) * r;
          ctx.beginPath();
          ctx.arc(x, y, 2 + amp * 3, 0, Math.PI * 2);
          ctx.fillStyle = `oklch(0.74 0.06 230 / ${0.5 + amp * 0.5})`;
          ctx.fill();
        }
      } else if (voiceState === 'processing') {
        // Orbiting particles collapsing inward
        const numParticles = 12;
        for (let i = 0; i < numParticles; i++) {
          const angle = (i / numParticles) * Math.PI * 2 + phase * 2.5;
          const r = 105 + Math.sin(phase * 3 + i) * 12;
          const x = cx + Math.cos(angle) * r;
          const y = cy + Math.sin(angle) * r;
          ctx.beginPath();
          ctx.arc(x, y, 2.5, 0, Math.PI * 2);
          ctx.fillStyle = `oklch(0.72 0.15 300 / 0.7)`;
          ctx.fill();
        }
        // Inner ring
        ctx.beginPath();
        ctx.arc(cx, cy, 95 + Math.sin(phase * 4) * 5, 0, Math.PI * 2);
        ctx.strokeStyle = `oklch(0.72 0.15 300 / 0.25)`;
        ctx.lineWidth = 1;
        ctx.stroke();
      } else if (voiceState === 'speaking') {
        // Concentric outward sound waves synced to TTS amplitude
        const waves = 5;
        for (let i = 0; i < waves; i++) {
          const offset = (phase * 80 + i * 28) % 120;
          const r = 90 + offset;
          const alpha = (1 - offset / 120) * (0.3 + speakerAmplitude * 0.5);
          ctx.beginPath();
          ctx.arc(cx, cy, r, 0, Math.PI * 2);
          ctx.strokeStyle = `oklch(0.75 0.09 160 / ${alpha})`;
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
      }

      animRef.current = requestAnimationFrame(draw);
    };

    draw();
    return () => cancelAnimationFrame(animRef.current);
  }, [voiceState, micAmplitude, speakerAmplitude]);

  if (voiceState === 'disabled') return null;

  return (
    <canvas
      ref={canvasRef}
      width={300}
      height={300}
      style={{
        position: 'absolute',
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        pointerEvents: 'none',
        zIndex: 0,
      }}
    />
  );
}

// ── Voice intro modal ─────────────────────────────────────────────────────────
function VoiceIntroModal({ onClose, wakeName, isSupported }: {
  onClose: () => void;
  wakeName: string;
  isSupported: boolean;
}) {
  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'oklch(0.08 0.01 255 / 0.85)',
        backdropFilter: 'blur(6px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '1rem',
      }}
    >
      <div
        className="acm-card"
        style={{
          maxWidth: 480, width: '100%',
          padding: '2rem',
          border: '1px solid oklch(0.84 0.16 82 / 0.3)',
          boxShadow: '0 0 40px oklch(0.84 0.16 82 / 0.08)',
          position: 'relative',
        }}
      >
        {/* Close */}
        <button
          onClick={onClose}
          style={{
            position: 'absolute', top: 14, right: 14,
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: 'var(--acm-fg-4)', padding: 4, borderRadius: 6,
          }}
        >
          <X size={16} />
        </button>

        {/* Header */}
        <div className="flex items-center gap-3 mb-5">
          <div style={{
            width: 36, height: 36, borderRadius: '50%',
            background: 'oklch(0.84 0.16 82 / 0.12)',
            border: '1px solid oklch(0.84 0.16 82 / 0.3)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
          }}>
            <Mic size={16} style={{ color: 'var(--acm-accent)' }} />
          </div>
          <div>
            <h2 className="text-base font-semibold" style={{ color: 'var(--acm-fg)' }}>
              Voice Interface
            </h2>
            <p className="text-xs" style={{ color: 'var(--acm-fg-4)' }}>How to talk to your agent</p>
          </div>
        </div>

        {/* Steps */}
        <div className="flex flex-col gap-3 mb-5">
          <div className="flex items-start gap-3 p-3 rounded-lg" style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)' }}>
            <Radio size={14} style={{ color: 'var(--acm-accent)', marginTop: 1, flexShrink: 0 }} />
            <div>
              <p className="text-xs font-semibold mb-0.5" style={{ color: 'var(--acm-fg)' }}>Always-on passive listening</p>
              <p className="text-xs" style={{ color: 'var(--acm-fg-3)' }}>
                Once enabled, the mic stays active in the background — but it only reacts when you say the wake word.
                Everything else is silently discarded.
              </p>
            </div>
          </div>

          <div className="flex items-start gap-3 p-3 rounded-lg" style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)' }}>
            <Zap size={14} style={{ color: 'oklch(0.74 0.06 230)', marginTop: 1, flexShrink: 0 }} />
            <div>
              <p className="text-xs font-semibold mb-0.5" style={{ color: 'var(--acm-fg)' }}>Wake word &rarr; command</p>
              <p className="text-xs" style={{ color: 'var(--acm-fg-3)' }}>
                Say{' '}
                <code className="mono px-1.5 py-0.5 rounded" style={{ background: 'oklch(0.84 0.16 82 / 0.15)', color: 'var(--acm-accent)', fontSize: 11 }}>
                  {wakeName || 'your assistant name'}
                </code>
                {' '}to wake up — then speak your command naturally.
                You can also say the wake word followed immediately by the command in one sentence.
              </p>
            </div>
          </div>

          <div className="flex items-start gap-3 p-3 rounded-lg" style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)' }}>
            <Volume2 size={14} style={{ color: 'var(--acm-ok)', marginTop: 1, flexShrink: 0 }} />
            <div>
              <p className="text-xs font-semibold mb-0.5" style={{ color: 'var(--acm-fg)' }}>Interrupt anytime</p>
              <p className="text-xs" style={{ color: 'var(--acm-fg-3)' }}>
                Say the wake word again while the agent is speaking to stop it and issue a new command immediately.
              </p>
            </div>
          </div>
        </div>

        {/* Wake word hint */}
        <div className="p-3 rounded-lg mb-5 flex items-center gap-2" style={{ background: 'oklch(0.84 0.16 82 / 0.07)', border: '1px solid oklch(0.84 0.16 82 / 0.2)' }}>
          <Info size={12} style={{ color: 'var(--acm-accent)', flexShrink: 0 }} />
          <p className="text-xs" style={{ color: 'var(--acm-fg-3)' }}>
            Your current wake word is{' '}
            <strong style={{ color: 'var(--acm-accent)' }}>{wakeName || '(set in Config → Voice)'}</strong>.
            You can change it anytime in{' '}
            <span className="mono" style={{ color: 'var(--acm-fg-2)', fontSize: 11 }}>Config → Voice</span>.
          </p>
        </div>

        {/* Browser warning if not supported */}
        {!isSupported && (
          <div className="flex items-start gap-2 p-3 rounded-lg mb-5" style={{ background: 'oklch(0.65 0.18 35 / 0.1)', border: '1px solid oklch(0.65 0.18 35 / 0.3)' }}>
            <AlertTriangle size={13} style={{ color: 'var(--acm-err)', marginTop: 1, flexShrink: 0 }} />
            <p className="text-xs" style={{ color: 'var(--acm-fg-3)' }}>
              Voice input requires <strong style={{ color: 'var(--acm-fg-2)' }}>Chrome or Edge</strong>.
              Your current browser does not support the Web Speech API.
              TTS playback still works on any browser.
            </p>
          </div>
        )}

        <button
          onClick={onClose}
          className="w-full py-2 rounded-lg text-sm font-semibold mono tracking-wider transition-all"
          style={{
            background: 'var(--acm-accent)',
            color: 'oklch(0.18 0.015 80)',
            border: 'none',
            cursor: 'pointer',
          }}
        >
          GOT IT
        </button>
      </div>
    </div>
  );
}

// DaemonContent is a child of AppLayout → inside VoiceProvider → useVoice() works
function DaemonContent() {
  const { agentState, activeSkin, setActiveSkin } = useTamagotchiStore();
  const thinkingLabel = useChatStore((s) => s.thinkingLabel);
  const isWaiting = useChatStore((s) => s.isWaitingResponse);
  const [showGuide, setShowGuide] = useState(false);
  const [showIntro, setShowIntro] = useState(false);
  const {
    voiceState, micAmplitude, speakerAmplitude, isSupported,
    activate, deactivate, config: voiceConfig,
    engineMode, setEngineMode, daemonStatus, startDaemon, stopDaemon,
    installVoiceDeps, isInstalling, isStarting, installLog,
    modelProgress, isModelReady, micDevices, selectedMicId, setSelectedMic,
  } = useVoice();
  const { fetchAPI } = useAPI();

  const [serverTtsVoices, setServerTtsVoices] = useState<ServerTTSVoice[]>([]);
  const [serverTtsVoice, setServerTtsVoiceState] = useState<string>('es-MX-DaliaNeural');

  useEffect(() => {
    fetchAPI('/api/voice/server-tts/voices').then(setServerTtsVoices).catch(() => {});
    fetchAPI('/api/voice/config').then((cfg: any) => {
      if (cfg?.server_tts_voice) setServerTtsVoiceState(cfg.server_tts_voice);
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setServerTtsVoice = useCallback((id: string) => {
    setServerTtsVoiceState(id);
    fetchAPI('/api/voice/config', {
      method: 'PATCH',
      body: JSON.stringify({ server_tts_voice: id }),
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const isVoiceActive = voiceState !== 'disabled';
  const voiceInfo = VOICE_STATE_INFO[voiceState];
  const isDaemonModelLoading = daemonStatus?.current_state === 'loading_model';

  // Show intro once per browser
  useEffect(() => {
    try {
      if (!localStorage.getItem(INTRO_STORAGE_KEY)) setShowIntro(true);
    } catch { /* localStorage unavailable */ }
  }, []);

  const dismissIntro = () => {
    try { localStorage.setItem(INTRO_STORAGE_KEY, '1'); } catch { /* */ }
    setShowIntro(false);
  };

  const info = STATE_INFO[agentState];
  const isPulsing = agentState === 'thinking' || agentState === 'working';

  return (
    <>
      {showIntro && (
        <VoiceIntroModal
          onClose={dismissIntro}
          wakeName={voiceConfig?.assistant_name ?? ''}
          isSupported={isSupported}
        />
      )}
      <div className="p-6 lg:p-8 max-w-4xl mx-auto">

        {/* ── Header ── */}
        <header className="mb-8">
          <span className="acm-breadcrumb">ACM / Daemon</span>
          <h1 className="text-2xl font-semibold" style={{ color: 'var(--acm-fg)' }}>
            Daemon
          </h1>
          <p className="text-sm mt-1 font-medium" style={{ color: 'var(--acm-accent)' }}>
            {voiceConfig?.assistant_name || 'OpenACM'}
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
                border: `1px solid ${isVoiceActive ? voiceInfo.color + '55' : 'var(--acm-border-strong)'}`,
                transition: 'border-color 0.4s ease',
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
                  position: 'relative',
                  zIndex: 1,
                }}
              >
                <ACMMark size={120} color="var(--acm-accent)" />
              </div>

              {/* Tamagotchi widget + Voice Aura overlay */}
              <div style={{ position: 'relative', width: 220, height: 220, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <VoiceAura voiceState={voiceState} micAmplitude={micAmplitude} speakerAmplitude={speakerAmplitude} />
                <div style={{ position: 'relative', zIndex: 1 }}>
                  <TamaPlaceholder size={200} />
                </div>
              </div>

              {/* Agent state badge pill */}
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
                <span className="text-sm font-bold tracking-widest mono" style={{ color: info.color }}>
                  {info.label}
                </span>
              </div>

              {/* Voice state badge — only when active */}
              {isVoiceActive && (
                <div
                  className="mt-2 flex items-center gap-2 px-3 py-1 rounded-full"
                  style={{
                    background: isDaemonModelLoading ? 'oklch(0.84 0.16 82 / 0.08)' : `${voiceInfo.color}14`,
                    border: `1px solid ${isDaemonModelLoading ? 'oklch(0.84 0.16 82 / 0.25)' : voiceInfo.color + '33'}`,
                  }}
                >
                  {isDaemonModelLoading
                    ? <span className="dot dot-accent acm-pulse" style={{ width: 7, height: 7 }} />
                    : voiceState === 'speaking'
                      ? <Volume2 size={11} style={{ color: voiceInfo.color }} />
                      : <Mic size={11} style={{ color: voiceInfo.color, opacity: voiceState === 'passive' ? 0.6 : 1 }} />
                  }
                  <span className="text-[11px] font-bold tracking-widest mono" style={{ color: isDaemonModelLoading ? 'var(--acm-accent)' : voiceInfo.color }}>
                    {isDaemonModelLoading ? 'LOADING MODEL' : voiceInfo.label}
                  </span>
                  {!isDaemonModelLoading && voiceConfig?.assistant_name && voiceState === 'passive' && (
                    <span className="text-[10px] mono" style={{ color: 'var(--acm-fg-4)' }}>
                      say &ldquo;{voiceConfig.assistant_name}&rdquo;
                    </span>
                  )}
                </div>
              )}

              {/* Sub-label */}
              <p className="mt-3 text-sm text-center min-h-[20px]" style={{ color: 'var(--acm-fg-3)' }}>
                {isWaiting && thinkingLabel
                  ? thinkingLabel
                  : isDaemonModelLoading
                    ? 'Downloading Whisper — takes ~1 min on first run…'
                    : isVoiceActive
                      ? voiceInfo.desc
                      : info.desc}
              </p>

              {/* Voice toggle button */}
              {isSupported && (
                <button
                  onClick={isVoiceActive ? deactivate : activate}
                  className="mt-5 flex items-center gap-2 px-5 py-2 rounded-full transition-all"
                  style={isVoiceActive ? {
                    background: `${voiceInfo.color}18`,
                    border: `1px solid ${voiceInfo.color}55`,
                    color: voiceInfo.color,
                  } : {
                    background: 'var(--acm-elev)',
                    border: '1px solid var(--acm-border)',
                    color: 'var(--acm-fg-3)',
                  }}
                >
                  {isVoiceActive
                    ? <><MicOff size={13} /><span className="text-xs mono font-bold tracking-wider">DISABLE VOICE</span></>
                    : <><Mic size={13} /><span className="text-xs mono font-bold tracking-wider">ENABLE VOICE</span></>
                  }
                </button>
              )}
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

            {/* ── Voice Engine mode selector ── */}
            <VoiceEngineCard
              engineMode={engineMode}
              onSetMode={setEngineMode}
              daemonStatus={daemonStatus}
              onStartDaemon={startDaemon}
              onStopDaemon={stopDaemon}
              onInstall={installVoiceDeps}
              isInstalling={isInstalling}
              isStarting={isStarting}
              installLog={installLog}
              micDevices={micDevices}
              selectedMicId={selectedMicId}
              onSetMic={setSelectedMic}
              serverTtsVoice={serverTtsVoice}
              onSetServerTtsVoice={setServerTtsVoice}
              serverTtsVoices={serverTtsVoices}
            />

            {/* ── Kokoro model download status (browser/auto mode) ── */}
            {(engineMode === 'browser' || engineMode === 'auto') && (
              <KokoroModelCard modelProgress={modelProgress} isModelReady={isModelReady} />
            )}

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
                      app/daemon/page.tsx
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
    </>
  );
}

export default function DaemonPage() {
  return (
    <AppLayout>
      <DaemonContent />
    </AppLayout>
  );
}
