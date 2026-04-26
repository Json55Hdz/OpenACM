'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useChatStore } from '@/stores/chat-store';
import { useAuthStore } from '@/stores/auth-store';
import { useTTS } from './use-tts';
import { useAPI } from './use-api';

// ─── Types ────────────────────────────────────────────────────────────────────

export type VoiceState =
  | 'disabled'    // mic off, feature inactive
  | 'passive'     // always listening, discarding everything (wake word gate)
  | 'activating'  // wake word just detected — brief flash
  | 'listening'   // actively capturing the command
  | 'processing'  // sent to LLM, waiting for response
  | 'speaking'    // TTS playing response
  | 'error';

export type VoiceEngineMode = 'browser' | 'server' | 'auto';

export interface VoiceConfig {
  tts_provider: string;
  tts_voice: string;
  voice_language: string;
  assistant_name: string;
  engine_mode?: VoiceEngineMode;
}

export interface DaemonStatus {
  is_running: boolean;
  engine_available: boolean;
  current_state: string;
  last_error: string;
  utterances_processed: number;
  deps: Record<string, boolean>;
}

export interface MicDevice {
  id: string;        // deviceId (browser) or index string (server)
  label: string;
  isDefault: boolean;
  source: 'browser' | 'server';
}

interface UseVoiceEngineReturn {
  voiceState: VoiceState;
  micAmplitude: number;
  speakerAmplitude: number;
  isSupported: boolean;
  activate: () => void;
  deactivate: () => void;
  config: VoiceConfig | null;
  engineMode: VoiceEngineMode;
  setEngineMode: (mode: VoiceEngineMode) => Promise<void>;
  daemonStatus: DaemonStatus | null;
  startDaemon: () => Promise<void>;
  stopDaemon: () => Promise<void>;
  installVoiceDeps: () => Promise<void>;
  isInstalling: boolean;
  isStarting: boolean;
  installLog: string[];
  modelProgress: number | null;
  isModelReady: boolean;
  micDevices: MicDevice[];
  selectedMicId: string;
  setSelectedMic: (id: string) => void;
}

// ─── Levenshtein — for fuzzy wake word matching ───────────────────────────────

function levenshtein(a: string, b: string): number {
  const m = a.length, n = b.length;
  const dp: number[][] = Array.from({ length: m + 1 }, (_, i) =>
    Array.from({ length: n + 1 }, (_, j) => (i === 0 ? j : j === 0 ? i : 0))
  );
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      dp[i][j] = a[i-1] === b[j-1]
        ? dp[i-1][j-1]
        : 1 + Math.min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1]);
  return dp[m][n];
}

function containsWakeWord(transcript: string, name: string): boolean {
  if (!name) return false;
  const lower = transcript.toLowerCase();
  const target = name.toLowerCase();
  // Direct inclusion
  if (lower.includes(target)) return true;
  // Fuzzy: check each word in transcript against the name
  const words = lower.split(/\s+/);
  return words.some(w => levenshtein(w, target) <= 1);
}

function extractCommand(transcript: string, name: string): string {
  const lower = transcript.toLowerCase();
  const target = name.toLowerCase();
  const idx = lower.indexOf(target);
  if (idx === -1) return transcript.trim();
  return transcript.slice(idx + target.length).replace(/^[,\s]+/, '').trim();
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useVoiceEngine(): UseVoiceEngineReturn {
  const [voiceState, setVoiceState] = useState<VoiceState>('disabled');
  const [config, setConfig] = useState<VoiceConfig | null>(null);
  const [micAmplitude, setMicAmplitude] = useState(0);
  const [engineMode, setEngineModeState] = useState<VoiceEngineMode>('browser');
  const [daemonStatus, setDaemonStatus] = useState<DaemonStatus | null>(null);
  const [micDevices, setMicDevices] = useState<MicDevice[]>([]);
  const [selectedMicId, setSelectedMicIdState] = useState<string>('default');
  const [isInstalling, setIsInstalling] = useState(false);
  const [installLog, setInstallLog] = useState<string[]>([]);
  const [isStarting, setIsStarting] = useState(false);
  const voiceStateRef = useRef<VoiceState>('disabled');
  const engineModeRef = useRef<VoiceEngineMode>(engineMode);
  const daemonPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const { fetchAPI } = useAPI();

  // In server/auto mode the daemon already handles TTS on the server machine.
  // Loading Kokoro ONNX in the browser (80 MB, main-thread inference) freezes the UI.
  // Use Web Speech API instead — it's instant and never blocks.
  const effectiveTTSProvider = engineMode === 'browser'
    ? ((config?.tts_provider as any) ?? 'kokoro')
    : 'browser';

  const { speak: ttsSpeak, stop: ttsStop, isSpeaking: ttsIsSpeaking, amplitude: ttsAmplitude, modelProgress, isModelReady } = useTTS({
    provider: effectiveTTSProvider,
    voice: config?.tts_voice ?? 'af_heart',
    language: config?.voice_language ?? 'en-US',
  });

  // Refs for Web Speech API
  const recogRef = useRef<SpeechRecognition | null>(null);
  const restartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const micAnalyserRef = useRef<AnalyserNode | null>(null);
  const micAnimRef = useRef<number>(0);

  const browserSpeechSupported = typeof window !== 'undefined' &&
    ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);
  // In server/auto mode the daemon provides the mic — no browser speech API needed
  const isSupported = engineMode === 'server'
    ? (daemonStatus?.engine_available ?? true)  // true until we know otherwise
    : engineMode === 'auto'
      ? (daemonStatus?.engine_available || browserSpeechSupported)
      : browserSpeechSupported;

  // Sync refs with state (closures capture refs, not state)
  const setState = useCallback((s: VoiceState) => {
    voiceStateRef.current = s;
    setVoiceState(s);
  }, []);
  useEffect(() => { engineModeRef.current = engineMode; }, [engineMode]);

  // ── Load config (retry when auth token is available) ─────────────────────
  const token = useAuthStore((s) => s.token);
  useEffect(() => {
    if (!token) return;
    fetchAPI('/api/voice/config')
      .then((cfg: VoiceConfig) => {
        setConfig(cfg);
        if (cfg.engine_mode) setEngineModeState(cfg.engine_mode);
      })
      .catch(() => {});
  }, [token]);

  // ── Engine mode setter (persists to server) ──────────────────────────────
  const setEngineMode = useCallback(async (mode: VoiceEngineMode) => {
    setEngineModeState(mode);
    try {
      await fetchAPI('/api/voice/config', {
        method: 'PATCH',
        body: JSON.stringify({ engine_mode: mode }),
      });
    } catch { /* ignore */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Daemon status polling (active when engine_mode is server/auto) ────────
  useEffect(() => {
    if (!token) return;
    const shouldPoll = engineMode === 'server' || engineMode === 'auto';
    if (!shouldPoll) {
      if (daemonPollRef.current) {
        clearInterval(daemonPollRef.current);
        daemonPollRef.current = null;
      }
      return;
    }
    const poll = () => {
      fetchAPI('/api/voice/daemon/status')
        .then((s: DaemonStatus) => setDaemonStatus(s))
        .catch(() => {});
    };
    poll();
    daemonPollRef.current = setInterval(poll, 3000);
    return () => {
      if (daemonPollRef.current) clearInterval(daemonPollRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, engineMode]);

  // ── Browser mic amplitude for VoiceAura in server/auto mode ────────────
  // The actual STT is handled by the server mic, but we open the browser mic
  // in monitor-only mode so the canvas animation reacts to the user's voice.
  useEffect(() => {
    if (engineMode !== 'server' && engineMode !== 'auto') return;
    if (!daemonStatus?.is_running) {
      stopMicAmplitude();
      return;
    }
    startMicAmplitude(selectedMicId !== 'default' ? selectedMicId : undefined);
    return () => stopMicAmplitude();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [daemonStatus?.is_running, engineMode]);

  // ── Mic device enumeration ────────────────────────────────────────────────
  useEffect(() => {
    if (!token) return;
    if (engineMode === 'server' || engineMode === 'auto') {
      // Fetch input devices from the server via sounddevice
      fetchAPI('/api/voice/devices')
        .then((devs: { index: number; name: string; default: boolean }[]) => {
          const list: MicDevice[] = [
            { id: 'default', label: 'System default', isDefault: true, source: 'server' },
            ...devs.map(d => ({
              id: String(d.index),
              label: d.name,
              isDefault: d.default,
              source: 'server' as const,
            })),
          ];
          setMicDevices(list);
        })
        .catch(() => {});
    } else {
      // Enumerate browser microphones
      if (typeof navigator === 'undefined' || !navigator.mediaDevices) return;
      navigator.mediaDevices.enumerateDevices()
        .then(devices => {
          const inputs = devices.filter(d => d.kind === 'audioinput');
          const list: MicDevice[] = inputs.length
            ? inputs.map((d, i) => ({
                id: d.deviceId || String(i),
                label: d.label || `Microphone ${i + 1}`,
                isDefault: d.deviceId === 'default' || i === 0,
                source: 'browser' as const,
              }))
            : [{ id: 'default', label: 'System default', isDefault: true, source: 'browser' }];
          setMicDevices(list);
        })
        .catch(() => {
          setMicDevices([{ id: 'default', label: 'System default', isDefault: true, source: 'browser' }]);
        });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, engineMode]);

  const setSelectedMic = useCallback((id: string) => {
    setSelectedMicIdState(id);
    // Persist to voice.config so daemon picks it up on next start
    fetchAPI('/api/voice/config', {
      method: 'PATCH',
      body: JSON.stringify({ mic_device: id === 'default' ? null : id }),
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Daemon start/stop ────────────────────────────────────────────────────
  const startDaemon = useCallback(async () => {
    setIsStarting(true);
    try {
      await fetchAPI('/api/voice/daemon/start', { method: 'POST', body: JSON.stringify({}) });
    } catch { /* error detail comes from status poll */ }
    // Wait briefly so a fast-failing _run() task has time to set last_error
    await new Promise(r => setTimeout(r, 600));
    try {
      const s: DaemonStatus = await fetchAPI('/api/voice/daemon/status');
      setDaemonStatus(s);
      if (s.is_running) setState('passive');
    } catch { /* ignore */ }
    setIsStarting(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setState]);

  const stopDaemon = useCallback(async () => {
    try {
      await fetchAPI('/api/voice/daemon/stop', { method: 'POST' });
      setDaemonStatus(prev => prev ? { ...prev, is_running: false, current_state: 'idle' } : null);
      setState('disabled');
    } catch { /* ignore */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setState]);

  const installVoiceDeps = useCallback(async () => {
    if (isInstalling) return;
    setIsInstalling(true);
    setInstallLog([]);
    try {
      const authStore = useAuthStore.getState();
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (authStore.token) headers['Authorization'] = `Bearer ${authStore.token}`;

      const resp = await fetch('/api/voice/daemon/install', { method: 'POST', headers });
      if (!resp.ok || !resp.body) {
        setInstallLog(['Error: server returned ' + resp.status]);
        setIsInstalling(false);
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop() ?? '';
        for (const part of parts) {
          for (const raw of part.split('\n')) {
            if (!raw.startsWith('data: ')) continue;
            const line = raw.slice(6);
            if (line === '__DONE__') {
              setInstallLog(prev => [...prev, '✓ Installation complete']);
              // Auto-start daemon after successful install
              try {
                await fetchAPI('/api/voice/daemon/start', { method: 'POST', body: JSON.stringify({}) });
              } catch { /* ignore */ }
              try {
                const s: DaemonStatus = await fetchAPI('/api/voice/daemon/status');
                setDaemonStatus(s);
                if (s.is_running) setState('passive');
              } catch { /* ignore */ }
              setIsInstalling(false);
              return;
            } else if (line.startsWith('__ERROR__')) {
              setInstallLog(prev => [...prev, '✗ ' + line.slice(9).trim()]);
              setIsInstalling(false);
              return;
            } else if (line) {
              setInstallLog(prev => [...prev, line]);
            }
          }
        }
      }
    } catch (err: any) {
      setInstallLog(prev => [...prev, '✗ ' + String(err)]);
    }
    setIsInstalling(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isInstalling, setState]);

  // ── Mic amplitude tracking ───────────────────────────────────────────────
  const startMicAmplitude = useCallback(async (deviceId?: string) => {
    try {
      const audioConstraint = deviceId && deviceId !== 'default'
        ? { deviceId: { exact: deviceId } }
        : true;
      const stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraint });
      micStreamRef.current = stream;
      const ctx = new AudioContext();
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      src.connect(analyser);
      micAnalyserRef.current = analyser;
      const buf = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteFrequencyData(buf);
        const avg = buf.reduce((a, b) => a + b, 0) / buf.length / 255;
        setMicAmplitude(avg);
        micAnimRef.current = requestAnimationFrame(tick);
      };
      tick();
    } catch { /* mic permission denied */ }
  }, []);

  const stopMicAmplitude = useCallback(() => {
    cancelAnimationFrame(micAnimRef.current);
    micStreamRef.current?.getTracks().forEach(t => t.stop());
    micStreamRef.current = null;
    setMicAmplitude(0);
  }, []);

  // ── Send command to chat via the store's registered sendMessage fn ──────
  const sendToChat = useCallback((text: string) => {
    if (!text.trim()) return;
    // Voice always targets the web channel — prevents routing to Telegram/cron if
    // the user happens to have a different target selected in the chat UI.
    useChatStore.getState().setTarget({ channel: 'web', user: 'web', title: 'Web Local' });
    // Show the user's spoken message in the chat so the conversation is visible.
    useChatStore.getState().addMessage({ content: text, role: 'user' });
    const fn = useChatStore.getState().sendMessageFn;
    if (!fn) return;
    setState('processing');
    (window as any).__voiceProcessing = true;
    fn(text);
  }, [setState]);

  // ── Listen for server daemon state changes via WebSocket ────────────────
  useEffect(() => {
    const handler = (e: Event) => {
      // Ignore daemon events in pure browser mode — they'd corrupt the Web Speech state
      if (engineMode === 'browser') return;
      const state = (e as CustomEvent<{ state: string }>).detail?.state;
      if (!state) return;
      if (state === 'passive') setState('passive');
      else if (state === 'activating') {
        setState('activating');
        // Safety fallback: if daemon doesn't send 'listening' quickly, transition ourselves
        setTimeout(() => {
          if (voiceStateRef.current === 'activating') setState('listening');
        }, 500);
      }
      else if (state === 'listening') setState('listening');
      else if (state === 'processing') setState('processing');
      else if (state === 'speaking') setState('speaking');
      else if (state === 'loading_model') { /* model still loading — keep current state */ }
      else if (state === 'idle' && voiceStateRef.current !== 'disabled') setState('disabled');
    };
    window.addEventListener('openacm:daemon_state', handler);
    return () => window.removeEventListener('openacm:daemon_state', handler);
  }, [setState, engineMode]);

  // ── Listen for LLM response and speak it ────────────────────────────────
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as { content?: string };
      const text = detail?.content;
      if (!text) return;
      if (voiceStateRef.current === 'disabled') return;
      // In server/auto mode: browser_tts_needed controls whether we speak here.
      // When edge-tts is installed the server speaks and sets browser_tts_needed=false.
      // When edge-tts is absent, browser_tts_needed=true and we speak here via Web Speech.
      // The check for 'disabled' above already guards unmounted state.
      setState('speaking');
      ttsSpeak(text).then(() => {
        if (voiceStateRef.current === 'speaking') setState('passive');
      });
    };
    window.addEventListener('openacm:voice_response', handler);
    return () => window.removeEventListener('openacm:voice_response', handler);
  }, [setState, ttsSpeak]);

  // ── Speech recognition setup ─────────────────────────────────────────────
  const buildRecognition = useCallback(() => {
    const SR: (new () => SpeechRecognition) | undefined =
      (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;
    if (!SR) return null;
    const r = new SR();
    r.continuous = true;
    r.interimResults = true;
    r.lang = config?.voice_language ?? 'en-US';
    r.maxAlternatives = 1;

    r.onresult = (event: SpeechRecognitionEvent) => {
      const state = voiceStateRef.current;
      if (state === 'disabled' || state === 'processing') return;

      // Interrupt detection: if speaking and wake word appears → stop TTS and listen
      if (state === 'speaking') {
        const interim = Array.from(event.results)
          .slice(event.resultIndex)
          .map(r => r[0].transcript)
          .join(' ');
        if (containsWakeWord(interim, config?.assistant_name ?? '')) {
          ttsStop();
          setState('activating');
          setTimeout(() => setState('listening'), 400);
        }
        return;
      }

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const transcript = result[0].transcript;
        const isFinal = result.isFinal;

        if (state === 'passive') {
          // Only check for wake word on interim/final results
          if (containsWakeWord(transcript, config?.assistant_name ?? '')) {
            const command = extractCommand(transcript, config?.assistant_name ?? '');
            setState('activating');
            setTimeout(() => {
              if (command.length > 2) {
                sendToChat(command);
              } else {
                setState('listening');
              }
            }, 350);
          }
        } else if (state === 'listening' && isFinal) {
          const text = transcript.trim();
          if (text.length > 1) sendToChat(text);
        }
      }
    };

    r.onend = () => {
      if (restartTimerRef.current) clearTimeout(restartTimerRef.current);
      // Auto-restart if we're still in an active voice state
      if (voiceStateRef.current !== 'disabled' && voiceStateRef.current !== 'error') {
        restartTimerRef.current = setTimeout(() => {
          try { recogRef.current?.start(); } catch { /* already started */ }
        }, 300);
      }
    };

    r.onerror = (e: SpeechRecognitionErrorEvent) => {
      if (e.error === 'not-allowed') {
        setState('error');
      }
      // aborted / no-speech are normal — onend will restart
    };

    return r;
  }, [config, sendToChat, setState, ttsStop]);

  // ── Activate / deactivate ────────────────────────────────────────────────
  const activate = useCallback(() => {
    // Server mode: delegate to daemon
    if (engineMode === 'server' || (engineMode === 'auto' && daemonStatus?.engine_available)) {
      startDaemon();
      return;
    }
    // Browser mode: Web Speech API
    if (!isSupported) return;
    const r = buildRecognition();
    if (!r) return;
    recogRef.current?.stop();
    recogRef.current = r;
    setState('passive');
    try { r.start(); } catch { /* already running */ }
    startMicAmplitude(selectedMicId !== 'default' ? selectedMicId : undefined);
  }, [engineMode, daemonStatus, startDaemon, isSupported, buildRecognition, setState, startMicAmplitude, selectedMicId]);

  const deactivate = useCallback(() => {
    // Server mode: stop daemon only if it's actually running
    if ((engineMode === 'server' || engineMode === 'auto') && daemonStatus?.is_running) {
      stopDaemon();
      return;
    }
    // Browser mode (or server with daemon already stopped): stop Web Speech API
    if (restartTimerRef.current) clearTimeout(restartTimerRef.current);
    recogRef.current?.stop();
    recogRef.current = null;
    ttsStop();
    stopMicAmplitude();
    setState('disabled');
  }, [engineMode, daemonStatus, stopDaemon, setState, ttsStop, stopMicAmplitude]);

  // Pause mic during TTS playback to avoid echo
  useEffect(() => {
    if (ttsIsSpeaking) {
      recogRef.current?.stop();
    } else if (voiceStateRef.current === 'speaking') {
      // tts finished → back to passive, restart recognition
      setState('passive');
      try { recogRef.current?.start(); } catch { /* already running */ }
    }
  }, [ttsIsSpeaking, setState]);

  // Cleanup on unmount only — use a ref so the effect never re-runs (avoids calling
  // deactivate() every time daemonStatus polls and recreates the callback).
  const deactivateRef = useRef(deactivate);
  useEffect(() => { deactivateRef.current = deactivate; });
  useEffect(() => () => { deactivateRef.current(); }, []);

  return {
    voiceState,
    micAmplitude,
    speakerAmplitude: ttsAmplitude,
    isSupported,
    activate,
    deactivate,
    config,
    engineMode,
    setEngineMode,
    daemonStatus,
    startDaemon,
    stopDaemon,
    installVoiceDeps,
    isInstalling,
    isStarting,
    installLog,
    modelProgress,
    isModelReady,
    micDevices,
    selectedMicId,
    setSelectedMic,
  };
}
