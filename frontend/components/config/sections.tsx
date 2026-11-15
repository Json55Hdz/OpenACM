'use client';

import { useState, useEffect } from 'react';
import { useAPI } from '@/hooks/use-api';
import { Bot, Save, Loader2, CheckCircle, Mic, Volume2 } from 'lucide-react';
import { toast } from 'sonner';
import { ConfigSection, Divider } from './primitives';

export function RagThresholdControl({ fetchAPI }: { fetchAPI: (url: string, opts?: RequestInit) => Promise<unknown> }) {
  const [threshold, setThreshold] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchAPI('/api/config/rag_threshold')
      .then((data: unknown) => {
        const d = data as { threshold?: number };
        if (typeof d?.threshold === 'number') setThreshold(d.threshold);
      })
      .catch(() => {});
  }, [fetchAPI]);

  const save = async (val: number) => {
    setSaving(true);
    try {
      await fetchAPI('/api/config/rag_threshold', {
        method: 'POST',
        body: JSON.stringify({ threshold: val }),
      });
      toast.success('Relevance threshold saved');
    } catch {
      toast.error('Failed to save threshold');
    } finally {
      setSaving(false);
    }
  };

  if (threshold === null) return null;

  const label =
    threshold <= 0.3
      ? 'Very strict — only near-identical matches'
      : threshold <= 0.5
      ? 'Balanced — recommended'
      : threshold <= 0.7
      ? 'Loose — more context, more noise'
      : 'Very loose — almost everything gets recalled';

  return (
    <div>
      <Divider />
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--acm-fg-2)' }}>Recall relevance threshold</div>
          <div style={{ fontSize: 11, color: 'var(--acm-fg-4)', marginTop: 3, maxWidth: 400 }}>
            Cosine distance cutoff for long-term memory recall. Lower = stricter (fewer but more accurate). Higher = more context but may pull unrelated memories.
          </div>
        </div>
        <span className="mono" style={{ fontSize: 13, color: 'var(--acm-accent)', flexShrink: 0 }}>
          {threshold.toFixed(2)}
        </span>
      </div>
      <input
        type="range"
        min={0.1}
        max={0.95}
        step={0.05}
        value={threshold}
        onChange={(e) => setThreshold(parseFloat(e.target.value))}
        onMouseUp={(e) => save(parseFloat((e.target as HTMLInputElement).value))}
        onTouchEnd={(e) => save(parseFloat((e.target as HTMLInputElement).value))}
        disabled={saving}
        style={{ width: '100%', accentColor: 'var(--acm-accent)' }}
      />
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--acm-fg-4)', marginTop: 4 }}>
        <span>0.1 — strict</span>
        <span style={{ fontStyle: 'italic', color: 'var(--acm-fg-3)' }}>{label}</span>
        <span>0.95 — loose</span>
      </div>
    </div>
  );
}

// ─── Nav item ─────────────────────────────────────────────────────────────────

// ── Assistant Identity Section ────────────────────────────────────────────────
export function AssistantSection() {
  const { fetchAPI } = useAPI();
  const [name, setName] = useState('');
  const [gender, setGender] = useState<'male' | 'female' | 'neutral'>('neutral');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchAPI('/api/config/assistant')
      .then((d: any) => { setName(d.name || 'OpenACM'); setGender(d.gender || 'neutral'); })
      .catch(() => {});
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await fetchAPI('/api/config/assistant', { method: 'PATCH', body: JSON.stringify({ name, gender }) });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch { /* ignore */ } finally { setSaving(false); }
  };

  const GENDERS: { value: 'male' | 'female' | 'neutral'; label: string; desc: string }[] = [
    { value: 'female', label: 'Female', desc: 'She/her voice & pronouns' },
    { value: 'male',   label: 'Male',   desc: 'He/him voice & pronouns' },
    { value: 'neutral', label: 'Neutral', desc: 'No gender assumption' },
  ];

  return (
    <ConfigSection id="section-assistant" title="Assistant Identity" subtitle="Name and voice personality for your AI companion" icon={Bot}>
      <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: 20 }}>
        {/* Name */}
        <div>
          <label className="label" style={{ display: 'block', marginBottom: 8 }}>Assistant Name</label>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="OpenACM"
            maxLength={100}
            className="mono"
            style={{
              width: '100%', padding: '8px 12px', borderRadius: 8,
              background: 'var(--acm-elev)', border: '1px solid var(--acm-border)',
              color: 'var(--acm-fg)', fontSize: 14,
              outline: 'none',
            }}
          />
          <p className="text-xs mt-1" style={{ color: 'var(--acm-fg-4)' }}>
            This is how the assistant identifies itself and its wake word.
          </p>
        </div>

        {/* Gender */}
        <div>
          <label className="label" style={{ display: 'block', marginBottom: 8 }}>Gender</label>
          <div style={{ display: 'flex', gap: 10 }}>
            {GENDERS.map(g => (
              <button
                key={g.value}
                onClick={() => setGender(g.value)}
                style={{
                  flex: 1, padding: '10px 8px', borderRadius: 8, cursor: 'pointer',
                  background: gender === g.value ? 'oklch(0.84 0.16 82 / 0.12)' : 'var(--acm-elev)',
                  border: gender === g.value ? '1px solid oklch(0.84 0.16 82 / 0.4)' : '1px solid var(--acm-border)',
                  color: gender === g.value ? 'var(--acm-accent)' : 'var(--acm-fg-3)',
                  transition: 'all 0.15s ease',
                  textAlign: 'center',
                }}
              >
                <p className="text-sm font-semibold mono">{g.label}</p>
                <p className="text-[11px] mt-0.5" style={{ color: gender === g.value ? 'var(--acm-accent-muted, var(--acm-fg-3))' : 'var(--acm-fg-4)' }}>{g.desc}</p>
              </button>
            ))}
          </div>
          <p className="text-xs mt-2" style={{ color: 'var(--acm-fg-4)' }}>
            Automatically selects a matching TTS voice (Kokoro: female → af_heart, male → am_adam).
          </p>
        </div>

        <button
          onClick={save}
          disabled={saving || !name.trim()}
          style={{
            alignSelf: 'flex-start', display: 'flex', alignItems: 'center', gap: 6,
            padding: '8px 18px', borderRadius: 8, cursor: saving ? 'default' : 'pointer',
            background: saved ? 'var(--acm-ok)' : 'var(--acm-accent)',
            color: 'oklch(0.18 0.015 80)', border: 'none', fontWeight: 600, fontSize: 13,
            opacity: saving || !name.trim() ? 0.6 : 1,
            transition: 'background 0.2s ease',
          }}
        >
          {saving ? <Loader2 size={13} className="animate-spin" /> : saved ? <CheckCircle size={13} /> : <Save size={13} />}
          {saved ? 'Saved!' : saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </ConfigSection>
  );
}

// ── Voice Config Section ──────────────────────────────────────────────────────
export function VoiceConfigSection() {
  const { fetchAPI } = useAPI();
  const [cfg, setCfg] = useState<any>(null);
  const [providers, setProviders] = useState<any[]>([]);
  const [voices, setVoices] = useState<any[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchAPI('/api/voice/config').then(setCfg).catch(() => {});
    fetchAPI('/api/voice/providers').then(setProviders).catch(() => {});
  }, []);

  useEffect(() => {
    if (!cfg) return;
    fetchAPI('/api/voice/voices').then(setVoices).catch(() => {});
  }, [cfg?.tts_provider]);

  const save = async (patch: Record<string, string>) => {
    setSaving(true);
    try {
      const updated = await fetchAPI('/api/voice/config', { method: 'PATCH', body: JSON.stringify(patch) });
      setCfg(updated);
      toast.success('Voice settings saved.');
    } catch {
      toast.error('Failed to save voice settings.');
    } finally {
      setSaving(false);
    }
  };

  if (!cfg) return null;

  const activeProvider = providers.find(p => p.id === cfg.tts_provider);

  return (
    <ConfigSection
      id="section-voice"
      title="Voice Interface"
      subtitle="Wake word detection, TTS provider, and voice language"
      icon={Mic}
    >
      {/* TTS Provider */}
      <div className="mb-5">
        <p className="label mb-3">TTS Provider</p>
        <div className="flex flex-col gap-2">
          {providers.map((p) => {
            const isActive = cfg.tts_provider === p.id;
            return (
              <button
                key={p.id}
                onClick={() => save({ tts_provider: p.id })}
                className="w-full flex items-start gap-3 px-4 py-3 rounded-lg text-left transition-all"
                style={isActive ? {
                  background: 'var(--acm-accent-soft)',
                  border: '1px solid oklch(0.84 0.16 82 / 0.25)',
                } : {
                  background: 'transparent',
                  border: '1px solid var(--acm-border)',
                }}
              >
                <Volume2 size={15} style={{ color: isActive ? 'var(--acm-accent)' : 'var(--acm-fg-4)', marginTop: 2, flexShrink: 0 }} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium" style={{ color: isActive ? 'var(--acm-accent)' : 'var(--acm-fg)' }}>
                      {p.name}
                    </span>
                    {p.offline && (
                      <span className="mono text-[9px] px-1.5 py-0.5 rounded" style={{ background: 'var(--acm-ok)22', color: 'var(--acm-ok)', border: '1px solid var(--acm-ok)33' }}>OFFLINE</span>
                    )}
                    {p.requires_key && (
                      <span className="mono text-[9px] px-1.5 py-0.5 rounded" style={{ background: 'var(--acm-warn)22', color: 'var(--acm-warn)', border: '1px solid var(--acm-warn)33' }}>API KEY</span>
                    )}
                  </div>
                  <p className="text-xs mt-0.5" style={{ color: 'var(--acm-fg-4)' }}>{p.description}</p>
                </div>
                {isActive && (
                  <span className="mono text-[10px] font-bold px-2 py-0.5 rounded-full shrink-0" style={{ background: 'var(--acm-accent)', color: 'oklch(0.18 0.015 80)' }}>ON</span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* API Key — only for providers that need it */}
      {activeProvider?.requires_key && (
        <div className="mb-5">
          <p className="label mb-2">API Key ({activeProvider.name})</p>
          <div className="flex gap-2">
            <input
              type="password"
              className="acm-input flex-1"
              placeholder={`${activeProvider.name} API key`}
              defaultValue={cfg.api_key || ''}
              onBlur={(e) => { if (e.target.value !== cfg.api_key) save({ api_key: e.target.value }); }}
            />
          </div>
        </div>
      )}

      {/* Voice selector */}
      {voices.length > 0 && (
        <div className="mb-5">
          <p className="label mb-2">Voice</p>
          <select
            className="acm-input w-full"
            value={cfg.tts_voice}
            onChange={(e) => save({ tts_voice: e.target.value })}
          >
            {voices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name} ({v.language}{v.gender && v.gender !== 'neutral' ? ` · ${v.gender}` : ''})
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Language */}
      <div className="mb-5">
        <p className="label mb-2">Recognition language (STT)</p>
        <select
          className="acm-input w-full"
          value={cfg.voice_language}
          onChange={(e) => save({ voice_language: e.target.value })}
        >
          <option value="en-US">English (US)</option>
          <option value="en-GB">English (UK)</option>
          <option value="es-ES">Spanish (Spain)</option>
          <option value="es-MX">Spanish (Mexico)</option>
          <option value="fr-FR">French</option>
          <option value="de-DE">German</option>
          <option value="pt-BR">Portuguese (Brazil)</option>
          <option value="it-IT">Italian</option>
          <option value="ja-JP">Japanese</option>
          <option value="zh-CN">Chinese (Simplified)</option>
        </select>
        <p className="text-xs mt-1" style={{ color: 'var(--acm-fg-4)' }}>
          Wake word is <strong style={{ color: 'var(--acm-fg-3)' }}>{cfg.assistant_name || '(not set)'}</strong> — set during onboarding.
        </p>
      </div>

      {saving && <p className="text-xs" style={{ color: 'var(--acm-fg-4)' }}>Saving…</p>}
    </ConfigSection>
  );
}
