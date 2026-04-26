'use client';

import { createContext, useContext } from 'react';
import { useVoiceEngine, VoiceState, VoiceConfig, VoiceEngineMode, DaemonStatus, MicDevice } from '@/hooks/use-voice-engine';

interface VoiceContextValue {
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

const VoiceContext = createContext<VoiceContextValue>({
  voiceState: 'disabled',
  micAmplitude: 0,
  speakerAmplitude: 0,
  isSupported: false,
  activate: () => {},
  deactivate: () => {},
  config: null,
  engineMode: 'browser',
  setEngineMode: async () => {},
  daemonStatus: null,
  startDaemon: async () => {},
  stopDaemon: async () => {},
  installVoiceDeps: async () => {},
  isInstalling: false,
  isStarting: false,
  installLog: [],
  modelProgress: null,
  isModelReady: false,
  micDevices: [],
  selectedMicId: 'default',
  setSelectedMic: () => {},
});

export function VoiceProvider({ children }: { children: React.ReactNode }) {
  const voice = useVoiceEngine();
  return <VoiceContext.Provider value={voice}>{children}</VoiceContext.Provider>;
}

export function useVoice() {
  return useContext(VoiceContext);
}
