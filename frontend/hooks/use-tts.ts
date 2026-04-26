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

  // Kokoro is loaded lazily on first speak() call — not pre-warmed on mount

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

    try {
      if (!audioCtxRef.current || audioCtxRef.current.state === 'closed') {
        audioCtxRef.current = new AudioContext();
      }
      const ctx = audioCtxRef.current;
      analyserRef.current = ctx.createAnalyser();
      analyserRef.current.fftSize = 256;
      analyserRef.current.connect(ctx.destination);
      const src = ctx.createMediaElementSource(audio);
      src.connect(analyserRef.current);
      _trackAmplitude(src);
    } catch { /* AudioContext not available */ }

    setIsSpeaking(true);
    return new Promise<void>((resolve) => {
      audio.onended = () => {
        cancelAnimationFrame(animFrameRef.current);
        setAmplitude(0);
        setIsSpeaking(false);
        URL.revokeObjectURL(url);
        resolve();
      };
      audio.onerror = () => { setIsSpeaking(false); resolve(); };
      audio.play().catch(() => { setIsSpeaking(false); resolve(); });
    });
  }, [_trackAmplitude]);

  const _speakBrowser = useCallback((text: string): Promise<void> => {
    return new Promise((resolve) => {
      window.speechSynthesis?.cancel();
      const utt = new SpeechSynthesisUtterance(text);
      utt.lang = options.language;
      utteranceRef.current = utt;

      const voices = window.speechSynthesis.getVoices();
      if (voices.length > 0) {
        const match = voices.find(v => v.lang.startsWith(options.language.split('-')[0]));
        if (match) utt.voice = match;
      }

      utt.onstart = () => setIsSpeaking(true);
      utt.onend = () => { setIsSpeaking(false); resolve(); };
      utt.onerror = () => { setIsSpeaking(false); resolve(); };
      window.speechSynthesis.speak(utt);
    });
  }, [options.language]);

  const _speakKokoro = useCallback(async (text: string): Promise<void> => {
    try {
      if (!kokoroRef.current) {
        setModelProgress(0);
        const { KokoroTTS } = await import('kokoro-js');
        // Run ONNX inference in a proxy Web Worker so the main thread never blocks.
        // This must be set before from_pretrained() initialises the ONNX backend.
        try {
          const { env } = await import('@huggingface/transformers');
          if (env?.backends?.onnx?.wasm) env.backends.onnx.wasm.proxy = true;
        } catch { /* transformers not directly importable — proxy will not be set */ }
        kokoroRef.current = await KokoroTTS.from_pretrained(
          'onnx-community/Kokoro-82M-ONNX',
          {
            dtype: 'q8',
            progress_callback: (info: any) => {
              if (info?.status === 'progress' && typeof info.progress === 'number') {
                setModelProgress(Math.round(info.progress));
              } else if (info?.status === 'ready' || info?.status === 'done') {
                setModelProgress(100);
              }
            },
          },
        );
        kokoroReadyRef.current = true;
        setIsModelReady(true);
        setModelProgress(null);
      }
      if (!kokoroReadyRef.current) return _speakBrowser(text);
      const audio = await kokoroRef.current.generate(text, { voice: options.voice });
      const blob = new Blob([audio.data], { type: 'audio/wav' });
      await _playAudioBlob(blob);
    } catch {
      kokoroReadyRef.current = false;
      kokoroRef.current = null;
      setIsModelReady(false);
      setModelProgress(null);
      return _speakBrowser(text);
    }
  }, [options.voice, _speakBrowser, _playAudioBlob]);

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
