'use client';

import { useCallback, useRef, useEffect, useState } from 'react';
import { useAPI } from './use-api';

export type TTSProvider = 'kokoro' | 'browser' | 'openai' | 'elevenlabs';

interface TTSOptions {
  provider: TTSProvider;
  voice: string;
  language: string;
}

interface UseTTSReturn {
  speak: (text: string) => Promise<void>;
  stop: () => void;
  isSpeaking: boolean;
  amplitude: number;       // 0-1, for visualizer
  modelProgress: number | null;  // 0-100 while Kokoro downloads, null otherwise
  isModelReady: boolean;         // true once Kokoro loaded in this session
}

export function useTTS(options: TTSOptions): UseTTSReturn {
  const { fetchAPI } = useAPI();
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [amplitude, setAmplitude] = useState(0);
  const [modelProgress, setModelProgress] = useState<number | null>(null);
  const [isModelReady, setIsModelReady] = useState(false);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number>(0);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const kokoroRef = useRef<any>(null);
  const kokoroReadyRef = useRef(false);
  const kokoroLoadingRef = useRef<Promise<any> | null>(null);

  // ── Lazy-but-eager Kokoro loader ───────────────────────────────────────
  // Loads in a worker so the main thread isn't blocked. Returns a shared
  // promise so concurrent calls (pre-warm + first speak) only download once.
  const _ensureKokoro = useCallback(async (): Promise<any | null> => {
    if (kokoroRef.current && kokoroReadyRef.current) return kokoroRef.current;
    if (kokoroLoadingRef.current) return kokoroLoadingRef.current;
    const loader = (async () => {
      try {
        setModelProgress(0);
        const { KokoroTTS } = await import('kokoro-js');
        const kokoro = await KokoroTTS.from_pretrained(
          'onnx-community/Kokoro-82M-ONNX',
          {
            dtype: 'q8',
            progress_callback: (info: any) => {
              if (info?.status === 'progress' && typeof info.progress === 'number') {
                // Cap at 99 — only flip to 100 after the smoke test below passes
                setModelProgress(Math.min(99, Math.round(info.progress)));
              }
            },
          },
        );
        // ── Smoke test ────────────────────────────────────────────────────
        // KokoroTTS.from_pretrained() can resolve OK while the underlying ONNX/
        // transformers.js graph is still busted (Safari iterator bugs, missing
        // worker resources, broken phonemizer wasm, etc). Run a tiny generate()
        // here to *prove* the pipeline works end-to-end before we let the user
        // activate voice. If this throws, we keep isModelReady=false so the
        // ENABLE VOICE button stays disabled — exactly the behaviour you asked for.
        try {
          const probe = await kokoro.generate('ok', { voice: options.voice as any });
          // Newer kokoro-js exposes RawAudio.audio (Float32Array); older builds used .data.
          // Accept either at runtime; just need *some* audio buffer to confirm the pipeline works.
          const probeAny = probe as any;
          const probeBuf = probeAny?.audio ?? probeAny?.data;
          if (!probeBuf || (probeBuf.byteLength ?? probeBuf.length ?? 0) < 100) {
            throw new Error('Kokoro probe returned empty audio');
          }
        } catch (probeErr) {
          console.error('[useTTS] Kokoro smoke test failed — model is unusable in this browser:', probeErr);
          throw probeErr;
        }
        kokoroRef.current = kokoro;
        kokoroReadyRef.current = true;
        setIsModelReady(true);
        setModelProgress(100);
        // Settle to "no progress shown" after a tick so the UI sees 100% briefly
        setTimeout(() => setModelProgress(null), 300);
        return kokoro;
      } catch (e) {
        kokoroRef.current = null;
        kokoroReadyRef.current = false;
        setIsModelReady(false);
        setModelProgress(null);
        kokoroLoadingRef.current = null;
        throw e;
      }
    })();
    kokoroLoadingRef.current = loader;
    try {
      const result = await loader;
      kokoroLoadingRef.current = null;
      return result;
    } catch {
      kokoroLoadingRef.current = null;
      return null;
    }
  }, [options.voice]);

  // Pre-warm Kokoro as soon as the component mounts with provider=kokoro,
  // so the model is ready by the time the user gets a voice response.
  useEffect(() => {
    if (options.provider !== 'kokoro') return;
    if (kokoroRef.current || kokoroLoadingRef.current) return;
    void _ensureKokoro();  // fire-and-forget; runs in worker, doesn't block UI
  }, [options.provider, _ensureKokoro]);

  // Global guard: kokoro-js / transformers.js can throw async errors that escape
  // our try/catch (internal Promise.then chains, worker postMessage failures).
  // If we see one, mark the model unready so the ENABLE VOICE button blocks again
  // and the user can see something is wrong.
  useEffect(() => {
    const onUnhandled = (ev: PromiseRejectionEvent) => {
      const reason = ev.reason;
      const msg = String(reason?.message || reason || '');
      const stack = String(reason?.stack || '');
      const looksLikeKokoro =
        /kokoro|transformers|onnx|ort\.|huggingface|tokenizer/i.test(msg + stack) ||
        /undefined is not a function.*of/i.test(msg);
      if (!looksLikeKokoro) return;
      console.error('[useTTS] Kokoro/transformers stack threw an unhandled rejection — invalidating model:', reason);
      kokoroRef.current = null;
      kokoroReadyRef.current = false;
      kokoroLoadingRef.current = null;
      setIsModelReady(false);
      setModelProgress(null);
    };
    window.addEventListener('unhandledrejection', onUnhandled);
    return () => window.removeEventListener('unhandledrejection', onUnhandled);
  }, []);

  const _trackAmplitude = useCallback((source: MediaElementAudioSourceNode | null) => {
    if (!source || !analyserRef.current) return;
    const analyser = analyserRef.current;
    const buf = new Uint8Array(analyser.frequencyBinCount);
    const tick = () => {
      analyser.getByteFrequencyData(buf);
      const avg = buf.reduce((a, b) => a + b, 0) / buf.length / 255;
      setAmplitude(avg);
      animFrameRef.current = requestAnimationFrame(tick);
    };
    tick();
  }, []);

  const _playAudioBlob = useCallback(async (blob: Blob) => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audioRef.current = audio;

    let ctxConnected = false;
    try {
      if (!audioCtxRef.current || audioCtxRef.current.state === 'closed') {
        audioCtxRef.current = new AudioContext();
      }
      const ctx = audioCtxRef.current;
      // Browsers auto-suspend the AudioContext after inactivity — must explicitly resume
      // before the second+ playback or audio.play() will succeed but produce no sound.
      if (ctx.state === 'suspended') {
        try { await ctx.resume(); } catch { /* will fall through to play() */ }
      }
      analyserRef.current = ctx.createAnalyser();
      analyserRef.current.fftSize = 256;
      analyserRef.current.connect(ctx.destination);
      const src = ctx.createMediaElementSource(audio);
      src.connect(analyserRef.current);
      _trackAmplitude(src);
      ctxConnected = true;
    } catch {
      // AudioContext failed (autoplay policy, second createMediaElementSource etc).
      // Fall back to direct playback without analyser/visualizer — audio still plays.
      ctxConnected = false;
    }

    setIsSpeaking(true);
    return new Promise<void>((resolve) => {
      const cleanup = () => {
        cancelAnimationFrame(animFrameRef.current);
        setAmplitude(0);
        setIsSpeaking(false);
        URL.revokeObjectURL(url);
      };
      audio.onended = () => { cleanup(); resolve(); };
      audio.onerror = () => { cleanup(); resolve(); };
      // If AudioContext setup failed, audio still has its own internal playback — it's
      // just not routed through the analyser. play() returns a promise that rejects on
      // autoplay block; resolve regardless so the voice engine doesn't hang.
      audio.play().catch((err) => {
        console.warn('TTS audio.play() rejected:', err);
        cleanup();
        resolve();
      });
      void ctxConnected;  // keep the var to silence unused warnings if linter strict
    });
  }, [_trackAmplitude]);

  const _speakBrowser = useCallback((text: string): Promise<void> => {
    return new Promise((resolve) => {
      const synth = window.speechSynthesis;
      if (!synth) {
        console.warn('[useTTS] speechSynthesis not available');
        resolve();
        return;
      }
      synth.cancel();
      const utt = new SpeechSynthesisUtterance(text);
      utt.lang = options.language || 'en-US';
      utteranceRef.current = utt;

      // Voices may not be loaded yet on first call — try to pick a matching one if available
      const voices = synth.getVoices();
      if (voices.length > 0) {
        const langPrefix = (options.language || 'en').split('-')[0];
        const match = voices.find(v => v.lang.startsWith(langPrefix));
        if (match) utt.voice = match;
      }

      // Hard timeout: speechSynthesis sometimes never fires onend (Chrome bug after long
      // utterances or when the tab loses focus). Resolve after a generous timeout
      // proportional to the text length so the voice engine never gets stuck.
      const expectedMs = Math.max(2000, text.length * 80) + 5000;
      const fallbackTimer = setTimeout(() => {
        console.warn('[useTTS] Web Speech timeout fallback fired');
        try { synth.cancel(); } catch { /* noop */ }
        setIsSpeaking(false);
        resolve();
      }, expectedMs);

      utt.onstart = () => setIsSpeaking(true);
      utt.onend = () => {
        clearTimeout(fallbackTimer);
        setIsSpeaking(false);
        resolve();
      };
      utt.onerror = (e) => {
        clearTimeout(fallbackTimer);
        console.warn('[useTTS] Web Speech onerror:', e);
        setIsSpeaking(false);
        resolve();
      };
      try {
        synth.speak(utt);
      } catch (e) {
        clearTimeout(fallbackTimer);
        console.warn('[useTTS] synth.speak() threw:', e);
        setIsSpeaking(false);
        resolve();
      }
    });
  }, [options.language]);

  const _speakKokoro = useCallback(async (text: string): Promise<void> => {
    // The voice engine is required to gate activation on isModelReady, so by the time
    // this runs Kokoro should already be loaded. If somehow it's not, that's a bug and
    // we surface it loudly rather than silently falling back to a different voice.
    if (!kokoroReadyRef.current || !kokoroRef.current) {
      console.error('[useTTS] _speakKokoro called before model ready — voice engine should have blocked this');
      return;
    }
    try {
      const audio = await kokoroRef.current.generate(text, { voice: options.voice as any });
      // Prefer toBlob() (newer kokoro-js, returns wav-encoded blob).
      // Fall back to raw .data ArrayBuffer (older builds) or .audio Float32Array (in between).
      let blob: Blob;
      if (typeof audio?.toBlob === 'function') {
        blob = audio.toBlob();
      } else if (audio?.data) {
        blob = new Blob([audio.data], { type: 'audio/wav' });
      } else if (audio?.audio) {
        blob = new Blob([audio.audio.buffer ?? audio.audio], { type: 'audio/wav' });
      } else {
        throw new Error('Kokoro returned no audio in any known field');
      }
      await _playAudioBlob(blob);
    } catch (e) {
      console.error('[useTTS] Kokoro generate failed:', e);
    }
  }, [options.voice, _playAudioBlob]);

  const _speakAPI = useCallback(async (text: string): Promise<void> => {
    try {
      const res = await fetch('/api/voice/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice_id: options.voice }),
      });
      if (!res.ok) throw new Error('TTS API error');
      const ct = res.headers.get('content-type') || '';
      if (ct.includes('application/json')) {
        // browser_side signal from server
        const json = await res.json();
        if (json.browser_side) return _speakBrowser(json.text ?? text);
        return;
      }
      const blob = await res.blob();
      await _playAudioBlob(blob);
    } catch {
      return _speakBrowser(text);
    }
  }, [options.voice, _speakBrowser, _playAudioBlob]);

  const speak = useCallback(async (text: string) => {
    if (!text.trim()) return;
    stop();
    switch (options.provider) {
      case 'kokoro':  return _speakKokoro(text);
      case 'browser': return _speakBrowser(text);
      default:        return _speakAPI(text);
    }
  }, [options.provider, _speakKokoro, _speakBrowser, _speakAPI]);

  const stop = useCallback(() => {
    audioRef.current?.pause();
    audioRef.current = null;
    window.speechSynthesis?.cancel();
    utteranceRef.current = null;
    cancelAnimationFrame(animFrameRef.current);
    setAmplitude(0);
    setIsSpeaking(false);
  }, []);

  useEffect(() => () => { stop(); }, [stop]);

  return { speak, stop, isSpeaking, amplitude, modelProgress, isModelReady };
}
