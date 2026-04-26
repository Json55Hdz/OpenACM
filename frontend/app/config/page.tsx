'use client';

import { useState, useEffect } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useConfig, useAPI, useMemoryStats, useClearMemory } from '@/hooks/use-api';
import {
  useSetModel,
  useProviderStatus,
  useGoogleStatus,
  useSaveGoogleCredentials,
  useDeleteGoogleCredentials,
  useStartGoogleAuth,
  useCustomProviders,
  useAddCustomProvider,
  useUpdateCustomProvider,
  useDeleteCustomProvider,
} from '@/hooks/use-setup';
import { ProviderSetupForm } from '@/components/setup/provider-setup-form';
import { TelegramSetup } from '@/components/setup/telegram-setup';
import { useSaveSetup } from '@/hooks/use-setup';
import { PROVIDERS, getProviderById } from '@/lib/providers';
import { translations } from '@/lib/translations';
import {
  Settings,
  Bot,
  Shield,
  Terminal,
  Save,
  Loader2,
  CheckCircle,
  MinusCircle,
  Copy,
  RefreshCw,
  ToggleLeft,
  ToggleRight,
  Send,
  Globe2,
  Trash2,
  Sparkles,
  Zap,
  Paintbrush,
  Plus,
  Pencil,
  Server,
  X,
  Wand2,
  Archive,
  FolderOpen,
  AlertTriangle,
  Brain,
  MessageSquare,
  Code2,
  Lightbulb,
  Database,
  ScrollText,
  Mic,
  Volume2,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

const tc = translations.config;

// ─── Section card wrapper ─────────────────────────────────────────────────────

function ConfigSection({
  title,
  subtitle,
  icon: Icon,
  children,
  id,
}: {
  title: string;
  subtitle?: string;
  icon: React.ElementType;
  children: React.ReactNode;
  id?: string;
}) {
  return (
    <div
      id={id}
      style={{
        background: 'var(--acm-card)',
        border: '1px solid var(--acm-border)',
        borderRadius: 'var(--acm-radius)',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          borderBottom: '1px solid var(--acm-border)',
          padding: '14px 20px',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            background: 'var(--acm-elev)',
            borderRadius: 6,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            color: 'var(--acm-accent)',
          }}
        >
          <Icon size={16} />
        </div>
        <div>
          <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--acm-fg)' }}>{title}</div>
          {subtitle && (
            <div className="mono" style={{ fontSize: 11, color: 'var(--acm-fg-4)', marginTop: 2 }}>
              {subtitle}
            </div>
          )}
        </div>
      </div>
      <div style={{ padding: '20px' }}>{children}</div>
    </div>
  );
}

// ─── Divider ──────────────────────────────────────────────────────────────────

function Divider() {
  return (
    <div style={{ height: 1, background: 'var(--acm-border)', margin: '16px 0' }} />
  );
}

// ─── Toggle row ───────────────────────────────────────────────────────────────

function ToggleRow({
  label,
  description,
  value,
  onToggle,
  disabled = false,
  badge,
}: {
  label: string;
  description?: string;
  value: boolean;
  onToggle: () => void;
  disabled?: boolean;
  badge?: React.ReactNode;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--acm-fg-2)', fontSize: 13, fontWeight: 500 }}>
          {label}
          {badge}
        </div>
        {description && (
          <p style={{ fontSize: 11, color: 'var(--acm-fg-4)', marginTop: 3 }}>{description}</p>
        )}
      </div>
      <button
        onClick={onToggle}
        disabled={disabled}
        style={{
          color: value ? 'var(--acm-accent)' : 'var(--acm-fg-4)',
          background: 'none',
          border: 'none',
          cursor: disabled ? 'not-allowed' : 'pointer',
          padding: 0,
          opacity: disabled ? 0.4 : 1,
          flexShrink: 0,
        }}
      >
        {value ? <ToggleRight size={26} /> : <ToggleLeft size={26} />}
      </button>
    </div>
  );
}

// ─── Stat tile ────────────────────────────────────────────────────────────────

function StatTile({
  label,
  value,
  sub,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon?: React.ElementType;
}) {
  return (
    <div
      style={{
        border: '1px solid var(--acm-border)',
        borderRadius: 'var(--acm-radius)',
        padding: '14px 16px',
        background: 'var(--acm-elev)',
      }}
    >
      <div className="label" style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
        {Icon && <Icon size={11} style={{ color: 'var(--acm-accent)' }} />}
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--acm-fg)', lineHeight: 1 }}>{value}</div>
      {sub && <div className="mono" style={{ fontSize: 10, color: 'var(--acm-fg-4)', marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

// ─── Info row ─────────────────────────────────────────────────────────────────

function InfoRow({ label, value, copyable = false }: { label: string; value: string; copyable?: boolean }) {
  const handleCopy = () => {
    navigator.clipboard.writeText(value);
    toast.success('Copied to clipboard');
  };
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '10px 0',
        borderBottom: '1px solid var(--acm-border)',
      }}
    >
      <span style={{ fontSize: 12, color: 'var(--acm-fg-3)' }}>{label}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span className="mono" style={{ fontSize: 12, color: 'var(--acm-fg-2)' }}>{value}</span>
        {copyable && (
          <button
            onClick={handleCopy}
            style={{ color: 'var(--acm-fg-4)', background: 'none', border: 'none', cursor: 'pointer', padding: 2 }}
          >
            <Copy size={12} />
          </button>
        )}
      </div>
    </div>
  );
}

// ─── RAG threshold control ────────────────────────────────────────────────────

function RagThresholdControl({ fetchAPI }: { fetchAPI: (url: string, opts?: RequestInit) => Promise<unknown> }) {
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

function NavItem({
  label,
  icon: Icon,
  active,
  onClick,
}: {
  label: string;
  icon: React.ElementType;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        width: '100%',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 12px',
        fontSize: 13,
        fontWeight: active ? 600 : 400,
        color: active ? 'var(--acm-accent)' : 'var(--acm-fg-3)',
        background: active ? 'var(--acm-card)' : 'transparent',
        borderRadius: 6,
        border: 'none',
        borderLeft: active ? '2px solid var(--acm-accent)' : '2px solid transparent',
        cursor: 'pointer',
        textAlign: 'left',
        transition: 'all 140ms ease',
      }}
      className={active ? '' : 'nav-inactive'}
    >
      <Icon size={14} style={{ flexShrink: 0 }} />
      {label}
    </button>
  );
}

// ─── Nav group label ──────────────────────────────────────────────────────────

function NavGroupLabel({ children }: { children: string }) {
  return (
    <div className="label" style={{ padding: '12px 12px 4px', color: 'var(--acm-fg-4)' }}>
      {children}
    </div>
  );
}

// ─── Provider card ────────────────────────────────────────────────────────────

function ProviderCard({
  name,
  description,
  active,
  configured,
  onClick,
}: {
  name: string;
  description?: string;
  active: boolean;
  configured: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        background: active
          ? 'var(--acm-accent-soft)'
          : configured
          ? 'var(--acm-elev)'
          : 'var(--acm-card)',
        border: `1px solid ${
          active
            ? 'oklch(0.84 0.16 82 / 0.25)'
            : 'var(--acm-border)'
        }`,
        borderRadius: 'var(--acm-radius)',
        padding: '12px 14px',
        textAlign: 'left',
        cursor: 'pointer',
        width: '100%',
        opacity: configured ? 1 : 0.5,
        transition: 'all 140ms ease',
      }}
    >
      <div
        style={{
          fontWeight: 600,
          fontSize: 13,
          color: active ? 'var(--acm-accent)' : 'var(--acm-fg-2)',
          marginBottom: 2,
        }}
      >
        {name}
      </div>
      {description && (
        <div className="mono" style={{ fontSize: 10, color: 'var(--acm-fg-4)', lineHeight: 1.4 }}>
          {description}
        </div>
      )}
      {active && (
        <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 4 }}>
          <span className="dot dot-ok" />
          <span style={{ fontSize: 10, color: 'var(--acm-ok)' }}>Active</span>
        </div>
      )}
    </button>
  );
}

// ─── Custom provider card (dashed) ────────────────────────────────────────────

function AddProviderCard({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: 'transparent',
        border: '1px dashed var(--acm-border-strong)',
        borderRadius: 'var(--acm-radius)',
        padding: '12px 14px',
        textAlign: 'center',
        cursor: 'pointer',
        width: '100%',
        color: 'var(--acm-fg-4)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 6,
        transition: 'all 140ms ease',
      }}
      className="nav-inactive"
    >
      <Plus size={16} />
      <span style={{ fontSize: 12 }}>Add Custom Provider</span>
    </button>
  );
}

// ─── Main config page ─────────────────────────────────────────────────────────

type NavSection =
  | 'assistant'
  | 'providers'
  | 'custom-providers'
  | 'model'
  | 'memory'
  | 'telegram'
  | 'google'
  | 'stitch'
  | 'router'
  | 'security'
  | 'resurrection'
  | 'voice'
  | 'raw';

const NAV_GROUPS: { group: string; items: { id: NavSection; label: string; icon: React.ElementType }[] }[] = [
  {
    group: 'AI',
    items: [
      { id: 'assistant', label: 'Assistant Identity', icon: Bot },
      { id: 'providers', label: 'LLM Providers', icon: Settings },
      { id: 'custom-providers', label: 'Custom Providers', icon: Server },
      { id: 'model', label: 'Default Model', icon: Bot },
      { id: 'memory', label: 'Memory & RAG', icon: Brain },
      { id: 'router', label: 'Intent Router', icon: Zap },
    ],
  },
  {
    group: 'Integrations',
    items: [
      { id: 'telegram', label: 'Telegram', icon: Send },
      { id: 'google', label: 'Google Services', icon: Globe2 },
      { id: 'stitch', label: 'Google Stitch', icon: Paintbrush },
    ],
  },
  {
    group: 'System',
    items: [
      { id: 'security', label: 'Security', icon: Shield },
      { id: 'voice', label: 'Voice Interface', icon: Mic },
      { id: 'resurrection', label: 'Code Resurrection', icon: Archive },
      { id: 'raw', label: 'Raw Config', icon: Terminal },
    ],
  },
];

// ── Assistant Identity Section ────────────────────────────────────────────────
function AssistantSection() {
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
function VoiceConfigSection() {
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

export default function ConfigPage() {
  const router = useRouter();
  const { fetchAPI } = useAPI();
  const [appVersion, setAppVersion] = useState('');
  const [activeSection, setActiveSection] = useState<NavSection>('providers');

  useEffect(() => {
    fetchAPI('/api/system/info')
      .then((d: any) => { if (d.version) setAppVersion(`v${d.version}`); })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const { config, model, isLoading, updateExecutionMode } = useConfig();
  const setModelMut = useSetModel();
  const saveSetup = useSaveSetup();

  // ─── Debug / verbose ────────────────────────────────────────────────────────
  const [isVerbose, setIsVerbose] = useState(false);

  // ─── Intent router ──────────────────────────────────────────────────────────
  const [routerEnabled, setRouterEnabled] = useState(true);
  const [routerObservation, setRouterObservation] = useState(false);
  const [routerThreshold, setRouterThreshold] = useState(0.88);
  const [routerStats, setRouterStats] = useState<Record<string, unknown> | null>(null);
  const [routerLoading, setRouterLoading] = useState(false);

  const toggleDebugMode = async (next: boolean) => {
    setIsVerbose(next);
    localStorage.setItem('openacm_debug_mode', next ? 'true' : 'false');
    try {
      await fetchAPI('/api/config/debug_mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: next }),
      });
    } catch { /* best-effort */ }
  };

  useEffect(() => {
    const saved = localStorage.getItem('openacm_debug_mode');
    if (saved !== null) setIsVerbose(saved === 'true');

    fetchAPI('/api/config/local_router')
      .then((d: any) => {
        setRouterEnabled(d.enabled ?? true);
        setRouterObservation(d.observation_mode ?? false);
        setRouterThreshold(d.confidence_threshold ?? 0.88);
        setRouterStats(d);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRouterToggle = async (field: 'enabled' | 'observation_mode', value: boolean) => {
    setRouterLoading(true);
    try {
      const body =
        field === 'enabled'
          ? { enabled: value }
          : { enabled: routerEnabled, observation_mode: value };
      const data: any = await fetchAPI('/api/config/local_router', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      setRouterEnabled(data.enabled);
      toast.success(
        field === 'enabled'
          ? value
            ? 'Local Router enabled'
            : 'Local Router disabled'
          : value
          ? 'Observation mode ON — router classifies but does not execute'
          : 'Fast-path active — router bypasses LLM for simple intents'
      );
    } catch {
      toast.error('Failed to update router config');
    } finally {
      setRouterLoading(false);
    }
  };

  const handleThresholdChange = async (val: number) => {
    setRouterThreshold(val);
    try {
      await fetchAPI('/api/config/local_router', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confidence_threshold: val }),
      });
    } catch { /* silent */ }
  };

  // ─── Code Resurrection ──────────────────────────────────────────────────────
  const [resurrectionPaths, setResurrectionPaths] = useState<string[]>([]);
  const [resurrectionIndexed, setResurrectionIndexed] = useState(0);
  const [newResurrectionPath, setNewResurrectionPath] = useState('');
  const [resurrectionLoading, setResurrectionLoading] = useState(false);

  useEffect(() => {
    fetchAPI('/api/config/resurrection_paths')
      .then((d: any) => {
        setResurrectionPaths(d.paths ?? []);
        setResurrectionIndexed(d.indexed_files ?? 0);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleAddResurrectionPath = async () => {
    const path = newResurrectionPath.trim();
    if (!path) return;
    setResurrectionLoading(true);
    try {
      const data: any = await fetchAPI('/api/config/resurrection_paths', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      setResurrectionPaths(data.paths ?? []);
      setNewResurrectionPath('');
      toast.success('Path added — watcher will index it during idle time');
    } catch {
      toast.error('Failed to add path — check that it exists on disk');
    } finally {
      setResurrectionLoading(false);
    }
  };

  const handleRemoveResurrectionPath = async (path: string) => {
    setResurrectionLoading(true);
    try {
      const data: any = await fetchAPI('/api/config/resurrection_paths', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      setResurrectionPaths(data.paths ?? []);
      toast.success('Path removed');
    } catch {
      toast.error('Failed to remove path');
    } finally {
      setResurrectionLoading(false);
    }
  };

  // ─── JSON config ────────────────────────────────────────────────────────────
  const [jsonConfig, setJsonConfig] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const handleSaveConfig = async () => {
    setIsSaving(true);
    try {
      JSON.parse(jsonConfig);
      toast.success('Configuration saved successfully');
    } catch {
      toast.error('Invalid JSON. Check the syntax.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleReloadConfig = () => {
    if (config) {
      setJsonConfig(JSON.stringify(config, null, 2));
      toast.success('Configuration reloaded');
    }
  };

  // ─── Telegram ───────────────────────────────────────────────────────────────
  const [telegramToken, setTelegramToken] = useState('');

  const handleTelegramSave = async () => {
    if (telegramToken.trim()) {
      await saveSetup.mutateAsync({ TELEGRAM_TOKEN: telegramToken.trim() });
      toast.success('Telegram token saved');
      setTelegramToken('');
    }
  };

  // ─── Stitch ─────────────────────────────────────────────────────────────────
  const [stitchKey, setStitchKey] = useState('');
  const [stitchSaving, setStitchSaving] = useState(false);

  const handleStitchSave = async () => {
    if (!stitchKey.trim()) return;
    setStitchSaving(true);
    try {
      await saveSetup.mutateAsync({ STITCH_API_KEY: stitchKey.trim() });
      setStitchKey('');
      toast.success('Stitch API key saved');
    } catch {
      toast.error('Failed to save Stitch API key');
    } finally {
      setStitchSaving(false);
    }
  };

  // ─── Model selection ────────────────────────────────────────────────────────
  const [customModel, setCustomModel] = useState('');
  const [customProvider, setCustomProvider] = useState('');
  const [savedCustomModels, setSavedCustomModels] = useState<Record<string, string[]>>({});
  const [modelParams, setModelParams] = useState<{ temperature?: number; max_tokens?: number; top_p?: number }>({});
  const [paramsSaving, setParamsSaving] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem('openacm_custom_models');
      if (stored) setSavedCustomModels(JSON.parse(stored));
    } catch {}
  }, []);

  const persistCustomModel = (modelName: string, providerId: string) => {
    setSavedCustomModels((prev) => {
      const list = prev[providerId] ?? [];
      if (list.includes(modelName)) return prev;
      const updated = { ...prev, [providerId]: [...list, modelName] };
      localStorage.setItem('openacm_custom_models', JSON.stringify(updated));
      return updated;
    });
  };

  const removeCustomModel = (modelName: string, providerId: string) => {
    setSavedCustomModels((prev) => {
      const updated = {
        ...prev,
        [providerId]: (prev[providerId] ?? []).filter((m) => m !== modelName),
      };
      localStorage.setItem('openacm_custom_models', JSON.stringify(updated));
      return updated;
    });
  };

  useEffect(() => {
    if (!model?.model || !model?.provider) return;
    fetchAPI(
      `/api/config/model-params?provider=${encodeURIComponent(model.provider)}&model=${encodeURIComponent(model.model)}`
    )
      .then((d) =>
        setModelParams(
          (d as { temperature?: number; max_tokens?: number; top_p?: number }) || {}
        )
      )
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model?.model, model?.provider]);

  const handleSaveParams = async () => {
    if (!model?.model || !model?.provider) return;
    setParamsSaving(true);
    try {
      await fetchAPI('/api/config/model-params', {
        method: 'PATCH',
        body: JSON.stringify({ provider: model.provider, model: model.model, ...modelParams }),
      });
      toast.success('Model parameters saved');
    } catch {
      toast.error('Failed to save parameters');
    } finally {
      setParamsSaving(false);
    }
  };

  const handleSetModel = (modelName: string, providerId: string) => {
    setModelMut.mutate({ model: modelName, provider: providerId });
  };

  const handleSetCustomModel = () => {
    const m = customModel.trim();
    if (!m || !customProvider) return;
    handleSetModel(m, customProvider);
    persistCustomModel(m, customProvider);
    setCustomModel('');
  };

  // ─── Compaction ─────────────────────────────────────────────────────────────
  const [compactThreshold, setCompactThreshold] = useState(25);
  const [compactKeepRecent, setCompactKeepRecent] = useState(6);
  const [compactionSaving, setCompactionSaving] = useState(false);

  useEffect(() => {
    fetchAPI('/api/config/compaction')
      .then((d: unknown) => {
        const data = d as { compact_threshold?: number; compact_keep_recent?: number };
        if (typeof data?.compact_threshold === 'number') setCompactThreshold(data.compact_threshold);
        if (typeof data?.compact_keep_recent === 'number') setCompactKeepRecent(data.compact_keep_recent);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const saveCompactionSettings = async (threshold: number, keepRecent: number) => {
    setCompactionSaving(true);
    try {
      await fetchAPI('/api/config/compaction', {
        method: 'POST',
        body: JSON.stringify({ compact_threshold: threshold, compact_keep_recent: keepRecent }),
      });
      toast.success('Compaction settings saved');
    } catch {
      toast.error('Failed to save compaction settings');
    } finally {
      setCompactionSaving(false);
    }
  };

  // ─── Memory ─────────────────────────────────────────────────────────────────
  const { data: memoryStats } = useMemoryStats();
  const clearMemory = useClearMemory();

  const handleClearMemory = async () => {
    if (
      !window.confirm(
        '¿Estás seguro de que quieres borrar TODA la memoria RAG? Esta acción no se puede deshacer.'
      )
    )
      return;
    try {
      const result = await clearMemory.mutateAsync();
      toast.success(`Memoria borrada — ${result?.deleted ?? 0} documentos eliminados`);
    } catch {
      toast.error('Error al borrar la memoria');
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  };

  // ─── Providers ──────────────────────────────────────────────────────────────
  const { data: providerStatus } = useProviderStatus();
  const { data: googleStatus } = useGoogleStatus();
  const { data: customProviders = [] } = useCustomProviders();
  const addCustomProvider = useAddCustomProvider();
  const updateCustomProvider = useUpdateCustomProvider();
  const deleteCustomProvider = useDeleteCustomProvider();

  const [showAddCustomProvider, setShowAddCustomProvider] = useState(false);
  const [cpForm, setCpForm] = useState({
    name: '',
    base_url: '',
    api_key: '',
    default_model: '',
    suggested_models: '',
  });
  const [editingCpId, setEditingCpId] = useState<string | null>(null);
  const [editCpForm, setEditCpForm] = useState({
    name: '',
    base_url: '',
    api_key: '',
    default_model: '',
    suggested_models: '',
  });

  const handleAddCustomProvider = async () => {
    const { name, base_url, api_key, default_model, suggested_models } = cpForm;
    if (!name.trim() || !base_url.trim()) return;
    const suggested = suggested_models
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    await addCustomProvider.mutateAsync({
      name: name.trim(),
      base_url: base_url.trim(),
      api_key: api_key.trim() || undefined,
      default_model: default_model.trim() || undefined,
      suggested_models: suggested.length ? suggested : undefined,
    });
    setCpForm({ name: '', base_url: '', api_key: '', default_model: '', suggested_models: '' });
    setShowAddCustomProvider(false);
  };

  const handleUpdateCustomProvider = async (id: string) => {
    const { name, base_url, api_key, default_model, suggested_models } = editCpForm;
    const suggested = suggested_models
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    await updateCustomProvider.mutateAsync({
      id,
      name: name.trim(),
      base_url: base_url.trim(),
      api_key: api_key.trim() || undefined,
      default_model: default_model.trim(),
      suggested_models: suggested,
    });
    setEditingCpId(null);
  };

  const saveGoogleCreds = useSaveGoogleCredentials();
  const deleteGoogleCreds = useDeleteGoogleCredentials();
  const startGoogleAuth = useStartGoogleAuth();
  const [googleCredJson, setGoogleCredJson] = useState('');

  // Build merged provider list
  const configuredProviders = Object.entries(providerStatus?.providers ?? {})
    .filter(([, enabled]) => enabled)
    .map(([id]) => {
      const staticDef = getProviderById(id);
      if (staticDef) return staticDef;
      const customDef = customProviders.find((cp) => cp.id === id);
      if (customDef)
        return {
          id: customDef.id,
          name: customDef.name,
          envVar: '',
          needsKey: customDef.has_key,
          suggestedModels: customDef.suggested_models,
          apiKeyUrl: '',
          description: `Custom — ${customDef.base_url}`,
        };
      return { id, name: id, envVar: '', needsKey: true, suggestedModels: [], apiKeyUrl: '', description: '' };
    });
  const activeProviderId = model?.provider || '';

  // ─── Section scroll helper ───────────────────────────────────────────────────
  const scrollTo = (id: NavSection) => {
    setActiveSection(id);
    const el = document.getElementById(`section-${id}`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  // ─── Render ──────────────────────────────────────────────────────────────────
  return (
    <AppLayout>
      <div
        style={{
          minHeight: '100vh',
          background: 'var(--acm-base)',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Page header */}
        <div style={{ padding: '24px 28px 0' }}>
          <span className="acm-breadcrumb">System / Config</span>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 700,
              color: 'var(--acm-fg)',
              margin: 0,
              marginBottom: 4,
            }}
          >
            {tc.title}
          </h1>
          <p style={{ fontSize: 13, color: 'var(--acm-fg-3)', margin: 0 }}>{tc.subtitle}</p>
        </div>

        {/* Body: left nav + right content */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            gap: 0,
            padding: '20px 28px 40px',
            alignItems: 'flex-start',
          }}
        >
          {/* ── Left sidebar nav ── */}
          <nav
            style={{
              width: 210,
              flexShrink: 0,
              position: 'sticky',
              top: 20,
              paddingRight: 16,
            }}
          >
            {NAV_GROUPS.map((group) => (
              <div key={group.group}>
                <NavGroupLabel>{group.group}</NavGroupLabel>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {group.items.map((item) => (
                    <NavItem
                      key={item.id}
                      label={item.label}
                      icon={item.icon}
                      active={activeSection === item.id}
                      onClick={() => scrollTo(item.id)}
                    />
                  ))}
                </div>
              </div>
            ))}

            {/* Save all */}
            <div style={{ marginTop: 24, paddingRight: 0 }}>
              <button
                onClick={handleSaveConfig}
                disabled={isSaving}
                className="btn-primary"
                style={{ width: '100%', justifyContent: 'center' }}
              >
                {isSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                Save all
              </button>
            </div>

            {/* System info */}
            <div style={{ marginTop: 20, padding: '12px 12px', background: 'var(--acm-card)', border: '1px solid var(--acm-border)', borderRadius: 'var(--acm-radius)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                <span className="dot dot-ok" />
                <span style={{ fontSize: 11, color: 'var(--acm-ok)' }}>System Online</span>
              </div>
              <div className="mono" style={{ fontSize: 10, color: 'var(--acm-fg-4)' }}>
                OpenACM {appVersion || 'v0.1.0'}
              </div>
              <div className="mono" style={{ fontSize: 10, color: 'var(--acm-fg-4)' }}>Next.js 16 · React 19</div>
              <button
                onClick={() => router.push('/onboarding?force=true')}
                style={{
                  marginTop: 10,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 5,
                  fontSize: 11,
                  color: 'var(--acm-accent)',
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  padding: 0,
                }}
              >
                <Wand2 size={11} />
                Setup Wizard
              </button>
            </div>
          </nav>

          {/* ── Right content ── */}
          <div
            style={{
              flex: 1,
              minWidth: 0,
              display: 'flex',
              flexDirection: 'column',
              gap: 20,
            }}
            className="acm-scroll"
          >

            {/* ── Assistant Identity ── */}
            <AssistantSection />

            {/* ── LLM Providers ── */}
            <ConfigSection
              id="section-providers"
              title={tc.providers.title}
              subtitle={tc.providers.subtitle}
              icon={Settings}
            >
              <ProviderSetupForm mode="config" />

              {/* Provider cards overview */}
              {configuredProviders.length > 0 && (
                <div>
                  <Divider />
                  <div className="label" style={{ marginBottom: 12 }}>Configured providers</div>
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))',
                      gap: 10,
                    }}
                  >
                    {configuredProviders.map((prov) => (
                      <ProviderCard
                        key={prov.id}
                        name={prov.name}
                        description={prov.description}
                        active={activeProviderId === prov.id}
                        configured={true}
                        onClick={() => {}}
                      />
                    ))}
                  </div>
                </div>
              )}
            </ConfigSection>

            {/* ── Custom Providers ── */}
            <ConfigSection
              id="section-custom-providers"
              title="Custom Providers"
              subtitle="OpenAI-compatible endpoints — LM Studio, Together AI, Groq, Ollama, etc."
              icon={Server}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {/* Existing custom providers */}
                {customProviders.map((cp) => (
                  <div
                    key={cp.id}
                    style={{
                      border: '1px solid var(--acm-border)',
                      borderRadius: 'var(--acm-radius)',
                      overflow: 'hidden',
                      background: 'var(--acm-elev)',
                    }}
                  >
                    {editingCpId === cp.id ? (
                      <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                          <div>
                            <label className="label" style={{ display: 'block', marginBottom: 8 }}>Name</label>
                            <input
                              className="acm-input"
                              value={editCpForm.name}
                              onChange={(e) => setEditCpForm((p) => ({ ...p, name: e.target.value }))}
                            />
                          </div>
                          <div>
                            <label className="label" style={{ display: 'block', marginBottom: 8 }}>Base URL</label>
                            <input
                              className="acm-input mono"
                              value={editCpForm.base_url}
                              onChange={(e) => setEditCpForm((p) => ({ ...p, base_url: e.target.value }))}
                            />
                          </div>
                          <div>
                            <label className="label" style={{ display: 'block', marginBottom: 8 }}>Default Model</label>
                            <input
                              className="acm-input mono"
                              placeholder="e.g. llama-3.1-8b"
                              value={editCpForm.default_model}
                              onChange={(e) => setEditCpForm((p) => ({ ...p, default_model: e.target.value }))}
                            />
                          </div>
                          <div>
                            <label className="label" style={{ display: 'block', marginBottom: 8 }}>
                              API Key (blank = keep)
                            </label>
                            <input
                              type="password"
                              className="acm-input"
                              placeholder="sk-..."
                              value={editCpForm.api_key}
                              onChange={(e) => setEditCpForm((p) => ({ ...p, api_key: e.target.value }))}
                            />
                          </div>
                        </div>
                        <div>
                          <label className="label" style={{ display: 'block', marginBottom: 8 }}>
                            Suggested Models (comma-separated)
                          </label>
                          <input
                            className="acm-input mono"
                            placeholder="model-a, model-b"
                            value={editCpForm.suggested_models}
                            onChange={(e) => setEditCpForm((p) => ({ ...p, suggested_models: e.target.value }))}
                          />
                        </div>
                        <div style={{ display: 'flex', gap: 8 }}>
                          <button
                            className="btn-primary"
                            onClick={() => handleUpdateCustomProvider(cp.id)}
                            disabled={updateCustomProvider.isPending}
                          >
                            {updateCustomProvider.isPending ? (
                              <Loader2 size={13} className="animate-spin" />
                            ) : (
                              <Save size={13} />
                            )}
                            Save
                          </button>
                          <button className="btn-secondary" onClick={() => setEditingCpId(null)}>
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div
                        style={{
                          padding: '10px 14px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: 12,
                        }}
                      >
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--acm-fg)' }}>
                              {cp.name}
                            </span>
                            {cp.has_key && (
                              <span
                                style={{
                                  fontSize: 10,
                                  color: 'var(--acm-ok)',
                                  border: '1px solid oklch(0.75 0.09 160 / 0.3)',
                                  borderRadius: 4,
                                  padding: '1px 6px',
                                }}
                              >
                                Key set
                              </span>
                            )}
                          </div>
                          <div
                            className="mono"
                            style={{
                              fontSize: 11,
                              color: 'var(--acm-fg-4)',
                              marginTop: 2,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {cp.base_url}
                          </div>
                          {cp.default_model && (
                            <div style={{ fontSize: 11, color: 'var(--acm-fg-3)', marginTop: 2 }}>
                              Default: <span className="mono">{cp.default_model}</span>
                            </div>
                          )}
                        </div>
                        <div style={{ display: 'flex', gap: 4 }}>
                          <button
                            onClick={() => {
                              setEditingCpId(cp.id);
                              setEditCpForm({
                                name: cp.name,
                                base_url: cp.base_url,
                                api_key: '',
                                default_model: cp.default_model,
                                suggested_models: cp.suggested_models.join(', '),
                              });
                            }}
                            title="Edit"
                            style={{
                              padding: 6,
                              color: 'var(--acm-fg-4)',
                              background: 'none',
                              border: 'none',
                              cursor: 'pointer',
                            }}
                          >
                            <Pencil size={13} />
                          </button>
                          <button
                            onClick={() => deleteCustomProvider.mutate(cp.id)}
                            disabled={deleteCustomProvider.isPending}
                            title="Delete"
                            style={{
                              padding: 6,
                              color: 'var(--acm-fg-4)',
                              background: 'none',
                              border: 'none',
                              cursor: 'pointer',
                            }}
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}

                {/* Add form or add button */}
                {showAddCustomProvider ? (
                  <div
                    style={{
                      border: '1px solid var(--acm-accent-soft, oklch(0.84 0.16 82 / 0.2))',
                      borderRadius: 'var(--acm-radius)',
                      padding: 16,
                      background: 'var(--acm-accent-soft)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 12,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--acm-fg)' }}>
                        New Custom Provider
                      </span>
                      <button
                        onClick={() => setShowAddCustomProvider(false)}
                        style={{ color: 'var(--acm-fg-4)', background: 'none', border: 'none', cursor: 'pointer' }}
                      >
                        <X size={15} />
                      </button>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                      <div>
                        <label className="label" style={{ display: 'block', marginBottom: 8 }}>
                          Name <span style={{ color: 'var(--acm-err)' }}>*</span>
                        </label>
                        <input
                          className="acm-input"
                          placeholder="e.g. LM Studio"
                          value={cpForm.name}
                          onChange={(e) => setCpForm((p) => ({ ...p, name: e.target.value }))}
                        />
                      </div>
                      <div>
                        <label className="label" style={{ display: 'block', marginBottom: 8 }}>
                          Base URL <span style={{ color: 'var(--acm-err)' }}>*</span>
                        </label>
                        <input
                          className="acm-input mono"
                          placeholder="http://localhost:1234/v1"
                          value={cpForm.base_url}
                          onChange={(e) => setCpForm((p) => ({ ...p, base_url: e.target.value }))}
                        />
                      </div>
                      <div>
                        <label className="label" style={{ display: 'block', marginBottom: 8 }}>
                          Default Model
                        </label>
                        <input
                          className="acm-input mono"
                          placeholder="e.g. llama-3.1-8b-instruct"
                          value={cpForm.default_model}
                          onChange={(e) => setCpForm((p) => ({ ...p, default_model: e.target.value }))}
                        />
                      </div>
                      <div>
                        <label className="label" style={{ display: 'block', marginBottom: 8 }}>
                          API Key (optional)
                        </label>
                        <input
                          type="password"
                          className="acm-input"
                          placeholder="sk-... or leave blank for local"
                          value={cpForm.api_key}
                          onChange={(e) => setCpForm((p) => ({ ...p, api_key: e.target.value }))}
                        />
                      </div>
                    </div>
                    <div>
                      <label className="label" style={{ display: 'block', marginBottom: 8 }}>
                        Suggested Models (comma-separated, optional)
                      </label>
                      <input
                        className="acm-input mono"
                        placeholder="model-a, model-b, model-c"
                        value={cpForm.suggested_models}
                        onChange={(e) => setCpForm((p) => ({ ...p, suggested_models: e.target.value }))}
                      />
                    </div>
                    <p style={{ fontSize: 11, color: 'var(--acm-fg-4)' }}>
                      Any OpenAI-compatible endpoint works — LM Studio, Ollama, Together AI, Groq, Perplexity, etc.
                    </p>
                    <button
                      className="btn-primary"
                      onClick={handleAddCustomProvider}
                      disabled={!cpForm.name.trim() || !cpForm.base_url.trim() || addCustomProvider.isPending}
                    >
                      {addCustomProvider.isPending ? (
                        <Loader2 size={13} className="animate-spin" />
                      ) : (
                        <Plus size={13} />
                      )}
                      Add Provider
                    </button>
                  </div>
                ) : (
                  <AddProviderCard onClick={() => setShowAddCustomProvider(true)} />
                )}
              </div>
            </ConfigSection>

            {/* ── Default Model ── */}
            <ConfigSection
              id="section-model"
              title={tc.model.title}
              subtitle="Active model used for all AI inference"
              icon={Bot}
            >
              {isLoading ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ height: 40, background: 'var(--acm-elev)', borderRadius: 6 }} />
                  <div style={{ height: 40, background: 'var(--acm-elev)', borderRadius: 6 }} />
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  {/* Current active indicator */}
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '10px 14px',
                      background: 'var(--acm-accent-soft)',
                      border: '1px solid oklch(0.84 0.16 82 / 0.2)',
                      borderRadius: 'var(--acm-radius)',
                    }}
                  >
                    <div>
                      <div className="label" style={{ marginBottom: 4 }}>Active</div>
                      <div className="mono" style={{ fontSize: 13, color: 'var(--acm-fg)' }}>
                        {model?.model || 'Not configured'}
                      </div>
                    </div>
                    {model?.provider && (
                      <span
                        style={{
                          fontSize: 11,
                          color: 'var(--acm-fg-3)',
                          padding: '2px 8px',
                          border: '1px solid var(--acm-border)',
                          borderRadius: 4,
                        }}
                      >
                        {model.provider}
                      </span>
                    )}
                  </div>

                  {/* Provider + model selector */}
                  {configuredProviders.length > 0 && (
                    <div>
                      <div className="label" style={{ marginBottom: 10 }}>Switch provider & model</div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                        {configuredProviders.map((prov) => {
                          const isActive = activeProviderId === prov.id;
                          const provDef = getProviderById(prov.id);
                          const suggestedModels = provDef?.suggestedModels ?? [];
                          const customSaved = (savedCustomModels[prov.id] ?? []).filter(
                            (m) => !suggestedModels.includes(m)
                          );

                          return (
                            <div
                              key={prov.id}
                              style={{
                                border: `1px solid ${isActive ? 'oklch(0.84 0.16 82 / 0.3)' : 'var(--acm-border)'}`,
                                borderRadius: 'var(--acm-radius)',
                                overflow: 'hidden',
                                background: isActive ? 'var(--acm-accent-soft)' : 'var(--acm-elev)',
                              }}
                            >
                              <div
                                style={{
                                  padding: '8px 12px',
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: 8,
                                  borderBottom: '1px solid var(--acm-border)',
                                }}
                              >
                                <span
                                  className="dot"
                                  style={{
                                    background: isActive ? 'var(--acm-accent)' : 'var(--acm-fg-4)',
                                  }}
                                />
                                <span
                                  style={{
                                    fontSize: 13,
                                    fontWeight: 600,
                                    color: isActive ? 'var(--acm-accent)' : 'var(--acm-fg-2)',
                                    flex: 1,
                                  }}
                                >
                                  {prov.name}
                                </span>
                                {isActive && (
                                  <span
                                    style={{
                                      fontSize: 10,
                                      fontWeight: 700,
                                      letterSpacing: '0.1em',
                                      textTransform: 'uppercase',
                                      color: 'var(--acm-accent)',
                                    }}
                                  >
                                    Active
                                  </span>
                                )}
                              </div>

                              {provDef?.cliDisclaimer && (
                                <div
                                  style={{
                                    margin: '8px 12px 0',
                                    padding: '8px 10px',
                                    background: 'oklch(0.84 0.16 82 / 0.05)',
                                    border: '1px solid oklch(0.84 0.16 82 / 0.2)',
                                    borderRadius: 6,
                                    fontSize: 11,
                                    color: 'var(--acm-warn)',
                                    display: 'flex',
                                    gap: 6,
                                  }}
                                >
                                  <span style={{ flexShrink: 0 }}>⚠</span>
                                  {provDef.cliDisclaimer}
                                </div>
                              )}

                              <div
                                style={{
                                  padding: '8px 12px 10px',
                                  display: 'flex',
                                  flexWrap: 'wrap',
                                  gap: 6,
                                }}
                              >
                                {suggestedModels.map((m) => {
                                  const isCurrent = model?.model === m && isActive;
                                  return (
                                    <button
                                      key={m}
                                      onClick={() => handleSetModel(m, prov.id)}
                                      disabled={setModelMut.isPending}
                                      className="mono"
                                      style={{
                                        padding: '3px 10px',
                                        fontSize: 11,
                                        borderRadius: 4,
                                        border: `1px solid ${isCurrent ? 'transparent' : 'var(--acm-border-strong)'}`,
                                        background: isCurrent ? 'var(--acm-accent)' : 'transparent',
                                        color: isCurrent ? 'oklch(0.18 0.015 80)' : 'var(--acm-fg-2)',
                                        cursor: 'pointer',
                                        fontWeight: isCurrent ? 700 : 400,
                                        transition: 'all 120ms ease',
                                        opacity: setModelMut.isPending ? 0.5 : 1,
                                      }}
                                    >
                                      {m}
                                    </button>
                                  );
                                })}
                                {customSaved.map((m) => {
                                  const isCurrent = model?.model === m && isActive;
                                  return (
                                    <div
                                      key={m}
                                      style={{ position: 'relative', display: 'flex', alignItems: 'center' }}
                                      className="group/cm"
                                    >
                                      <button
                                        onClick={() => handleSetModel(m, prov.id)}
                                        disabled={setModelMut.isPending}
                                        className="mono"
                                        style={{
                                          padding: '3px 22px 3px 10px',
                                          fontSize: 11,
                                          borderRadius: 4,
                                          border: `1px solid ${isCurrent ? 'transparent' : 'var(--acm-border-strong)'}`,
                                          background: isCurrent ? 'var(--acm-accent)' : 'transparent',
                                          color: isCurrent ? 'oklch(0.18 0.015 80)' : 'var(--acm-fg-3)',
                                          cursor: 'pointer',
                                          opacity: setModelMut.isPending ? 0.5 : 1,
                                        }}
                                      >
                                        {m}
                                      </button>
                                      <button
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          removeCustomModel(m, prov.id);
                                        }}
                                        style={{
                                          position: 'absolute',
                                          right: 4,
                                          fontSize: 12,
                                          color: 'var(--acm-fg-4)',
                                          background: 'none',
                                          border: 'none',
                                          cursor: 'pointer',
                                          lineHeight: 1,
                                        }}
                                        title="Remove"
                                      >
                                        ×
                                      </button>
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Custom model name input */}
                  <div>
                    <Divider />
                    <label className="label" style={{ display: 'block', marginBottom: 10 }}>
                      Custom model name
                    </label>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <select
                        value={customProvider}
                        onChange={(e) => setCustomProvider(e.target.value)}
                        style={{
                          padding: '7px 10px',
                          background: 'var(--acm-elev)',
                          border: '1px solid var(--acm-border)',
                          borderRadius: 6,
                          color: 'var(--acm-fg-2)',
                          fontSize: 12,
                          outline: 'none',
                          cursor: 'pointer',
                        }}
                      >
                        <option value="">Provider</option>
                        {configuredProviders.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                      <input
                        type="text"
                        className="acm-input mono"
                        style={{ flex: 1 }}
                        value={customModel}
                        onChange={(e) => setCustomModel(e.target.value)}
                        placeholder="e.g. gpt-4o-mini"
                        onKeyDown={(e) => e.key === 'Enter' && handleSetCustomModel()}
                      />
                      <button
                        className="btn-secondary"
                        onClick={handleSetCustomModel}
                        disabled={!customModel.trim() || !customProvider || setModelMut.isPending}
                      >
                        {setModelMut.isPending ? <Loader2 size={13} className="animate-spin" /> : 'Set'}
                      </button>
                    </div>
                  </div>

                  {/* Model parameters */}
                  {model?.model && (
                    <div>
                      <Divider />
                      <div className="label" style={{ marginBottom: 12 }}>
                        Parameters for{' '}
                        <span className="mono" style={{ color: 'var(--acm-accent)' }}>
                          {model.model}
                        </span>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 14 }}>
                        <div>
                          <div
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              marginBottom: 6,
                            }}
                          >
                            <label className="label">Temperature</label>
                            <span className="mono" style={{ fontSize: 11, color: 'var(--acm-accent)' }}>
                              {modelParams.temperature ?? 0.7}
                            </span>
                          </div>
                          <input
                            type="range"
                            min="0"
                            max="2"
                            step="0.05"
                            value={modelParams.temperature ?? 0.7}
                            onChange={(e) =>
                              setModelParams((p) => ({ ...p, temperature: parseFloat(e.target.value) }))
                            }
                            style={{ width: '100%', accentColor: 'var(--acm-accent)' }}
                          />
                        </div>
                        <div>
                          <div
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              marginBottom: 6,
                            }}
                          >
                            <label className="label">Top P</label>
                            <span className="mono" style={{ fontSize: 11, color: 'var(--acm-accent)' }}>
                              {modelParams.top_p ?? '—'}
                            </span>
                          </div>
                          <input
                            type="range"
                            min="0"
                            max="1"
                            step="0.05"
                            value={modelParams.top_p ?? 1}
                            onChange={(e) =>
                              setModelParams((p) => ({ ...p, top_p: parseFloat(e.target.value) }))
                            }
                            style={{ width: '100%', accentColor: 'var(--acm-accent)' }}
                          />
                        </div>
                      </div>
                      <div style={{ marginBottom: 14 }}>
                        <label className="label" style={{ display: 'block', marginBottom: 8 }}>
                          Max Tokens{' '}
                          <span style={{ color: 'var(--acm-fg-4)', fontWeight: 400 }}>
                            (0 = model default)
                          </span>
                        </label>
                        <input
                          type="number"
                          min="0"
                          step="256"
                          className="acm-input mono"
                          value={modelParams.max_tokens ?? 0}
                          onChange={(e) =>
                            setModelParams((p) => ({ ...p, max_tokens: parseInt(e.target.value) || 0 }))
                          }
                        />
                      </div>
                      <button
                        className="btn-primary"
                        onClick={handleSaveParams}
                        disabled={paramsSaving}
                        style={{ width: '100%', justifyContent: 'center' }}
                      >
                        {paramsSaving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                        Save parameters
                      </button>
                    </div>
                  )}
                </div>
              )}
            </ConfigSection>

            {/* ── Memory & RAG ── */}
            <ConfigSection
              id="section-memory"
              title="Memory & RAG"
              subtitle="vector-memory · long-term recall · auto-compaction"
              icon={Brain}
            >
              {memoryStats?.status === 'unavailable' ? (
                <p style={{ fontSize: 13, color: 'var(--acm-fg-4)' }}>
                  RAG engine unavailable or not yet initialized.
                </p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                  {/* System prompt textarea placeholder */}
                  <div>
                    <label className="label" style={{ display: 'block', marginBottom: 10 }}>
                      System Prompt
                    </label>
                    <textarea
                      rows={4}
                      className="acm-input mono"
                      style={{ resize: 'vertical', fontSize: 12, lineHeight: 1.6 }}
                      placeholder="Optional system prompt injected before every conversation..."
                    />
                  </div>

                  {/* Data stat tiles */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                    <StatTile
                      label="Total documents"
                      value={memoryStats?.total ?? 0}
                      icon={Database}
                    />
                    <StatTile
                      label="Storage"
                      value={formatBytes(memoryStats?.size_bytes ?? 0)}
                      icon={FolderOpen}
                    />
                    <StatTile
                      label="Notes & facts"
                      value={memoryStats?.by_type?.note ?? 0}
                      icon={Lightbulb}
                    />
                  </div>

                  {/* Memory type breakdown */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                    {[
                      { key: 'note', label: 'Notes', Icon: Lightbulb, color: 'var(--acm-warn)' },
                      { key: 'conversation', label: 'Conversations', Icon: MessageSquare, color: 'var(--acm-ok)' },
                      { key: 'code_archive', label: 'Code archives', Icon: Code2, color: 'var(--acm-accent)' },
                    ].map(({ key, label, Icon, color }) => {
                      const count = memoryStats?.by_type?.[key] ?? 0;
                      return (
                        <div
                          key={key}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 10,
                            padding: '12px 14px',
                            background: 'var(--acm-elev)',
                            border: '1px solid var(--acm-border)',
                            borderRadius: 'var(--acm-radius)',
                          }}
                        >
                          <Icon size={16} style={{ color, flexShrink: 0 }} />
                          <div>
                            <div style={{ fontSize: 11, color: 'var(--acm-fg-4)' }}>{label}</div>
                            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--acm-fg)' }}>{count}</div>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* RAG threshold slider */}
                  <RagThresholdControl fetchAPI={fetchAPI} />

                  {/* Auto-compaction */}
                  <div>
                    <Divider />
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        marginBottom: 6,
                      }}
                    >
                      <ScrollText size={14} style={{ color: 'var(--acm-accent)' }} />
                      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--acm-fg-2)' }}>
                        Auto-compaction
                      </span>
                      {compactionSaving && (
                        <Loader2 size={12} className="animate-spin" style={{ color: 'var(--acm-fg-4)', marginLeft: 'auto' }} />
                      )}
                    </div>
                    <p style={{ fontSize: 11, color: 'var(--acm-fg-4)', marginBottom: 16, lineHeight: 1.6 }}>
                      When a conversation gets long, older messages are summarized to free up context. Recent messages are always kept verbatim.
                    </p>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                      {/* Compact after N messages */}
                      <div>
                        <div
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            marginBottom: 6,
                          }}
                        >
                          <label className="label">Compact after</label>
                          <span className="mono" style={{ fontSize: 11, color: 'var(--acm-accent)' }}>
                            {compactThreshold} messages
                          </span>
                        </div>
                        <input
                          type="range"
                          min={5}
                          max={100}
                          step={5}
                          value={compactThreshold}
                          onChange={(e) => setCompactThreshold(Number(e.target.value))}
                          onMouseUp={(e) =>
                            saveCompactionSettings(
                              Number((e.target as HTMLInputElement).value),
                              compactKeepRecent
                            )
                          }
                          onTouchEnd={(e) =>
                            saveCompactionSettings(
                              Number((e.target as HTMLInputElement).value),
                              compactKeepRecent
                            )
                          }
                          style={{ width: '100%', accentColor: 'var(--acm-accent)' }}
                        />
                        <div
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            fontSize: 10,
                            color: 'var(--acm-fg-4)',
                            marginTop: 4,
                          }}
                        >
                          <span>5 — very often</span>
                          <span>100 — rarely</span>
                        </div>
                      </div>

                      {/* Keep recent N intact */}
                      <div>
                        <div
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            marginBottom: 6,
                          }}
                        >
                          <label className="label">Keep recent messages intact</label>
                          <span className="mono" style={{ fontSize: 11, color: 'var(--acm-accent)' }}>
                            {compactKeepRecent} messages
                          </span>
                        </div>
                        <input
                          type="range"
                          min={2}
                          max={20}
                          step={1}
                          value={compactKeepRecent}
                          onChange={(e) => setCompactKeepRecent(Number(e.target.value))}
                          onMouseUp={(e) =>
                            saveCompactionSettings(
                              compactThreshold,
                              Number((e.target as HTMLInputElement).value)
                            )
                          }
                          onTouchEnd={(e) =>
                            saveCompactionSettings(
                              compactThreshold,
                              Number((e.target as HTMLInputElement).value)
                            )
                          }
                          style={{ width: '100%', accentColor: 'var(--acm-accent)' }}
                        />
                        <div
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            fontSize: 10,
                            color: 'var(--acm-fg-4)',
                            marginTop: 4,
                          }}
                        >
                          <span>2 — minimum</span>
                          <span>20 — more recent context</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Danger zone — clear memory */}
                  <div>
                    <Divider />
                    <button
                      onClick={handleClearMemory}
                      disabled={clearMemory.isPending || (memoryStats?.total ?? 0) === 0}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        padding: '7px 14px',
                        background: 'oklch(0.68 0.13 22 / 0.08)',
                        border: '1px solid oklch(0.68 0.13 22 / 0.35)',
                        borderRadius: 'var(--acm-radius)',
                        color: 'var(--acm-err)',
                        fontSize: 13,
                        cursor: 'pointer',
                        opacity: clearMemory.isPending || (memoryStats?.total ?? 0) === 0 ? 0.4 : 1,
                        transition: 'all 140ms ease',
                      }}
                    >
                      <Trash2 size={14} />
                      Clear all memory ({memoryStats?.total ?? 0} docs)
                    </button>
                  </div>
                </div>
              )}
            </ConfigSection>

            {/* ── Intent Router ── */}
            <ConfigSection
              id="section-router"
              title="Local Intent Router"
              subtitle="Hybrid local/cloud — bypasses LLM for simple intents"
              icon={Zap}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                {/* Enable */}
                <div style={{ padding: '10px 0' }}>
                  <ToggleRow
                    label="Enable Local Router"
                    description="Classify intents locally using sentence-transformers"
                    value={routerEnabled}
                    onToggle={() => {
                      setRouterEnabled(!routerEnabled);
                      handleRouterToggle('enabled', !routerEnabled);
                    }}
                    disabled={routerLoading}
                  />
                </div>
                <Divider />

                {/* Observation mode */}
                <div style={{ padding: '10px 0' }}>
                  <ToggleRow
                    label="Observation Mode"
                    description="ON = classify only, log stats, never execute. OFF = fast-path active"
                    value={routerObservation}
                    onToggle={() => {
                      setRouterObservation(!routerObservation);
                      handleRouterToggle('observation_mode', !routerObservation);
                    }}
                    disabled={routerLoading || !routerEnabled}
                  />
                </div>
                <Divider />

                {/* Confidence threshold */}
                <div style={{ padding: '10px 0' }}>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      marginBottom: 10,
                    }}
                  >
                    <span style={{ fontSize: 13, color: 'var(--acm-fg-2)', fontWeight: 500 }}>
                      Confidence Threshold
                    </span>
                    <span className="mono" style={{ fontSize: 13, color: 'var(--acm-accent)' }}>
                      {routerThreshold.toFixed(2)}
                    </span>
                  </div>
                  <input
                    type="range"
                    min="0.50"
                    max="1.00"
                    step="0.01"
                    value={routerThreshold}
                    onChange={(e) => setRouterThreshold(parseFloat(e.target.value))}
                    onMouseUp={(e) =>
                      handleThresholdChange(parseFloat((e.target as HTMLInputElement).value))
                    }
                    disabled={!routerEnabled}
                    style={{
                      width: '100%',
                      accentColor: 'var(--acm-accent)',
                      opacity: routerEnabled ? 1 : 0.4,
                    }}
                  />
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      fontSize: 10,
                      color: 'var(--acm-fg-4)',
                      marginTop: 4,
                    }}
                  >
                    <span>0.50 — aggressive</span>
                    <span>1.00 — conservative</span>
                  </div>
                </div>

                {/* Stats */}
                {routerStats && (
                  <>
                    <Divider />
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                      {[
                        { label: 'Classified', value: String(routerStats.total_classified ?? 0) },
                        { label: 'Fast-path', value: String(routerStats.fast_path_eligible ?? 0) },
                        { label: 'Savings', value: `${routerStats.potential_savings_pct ?? 0}%` },
                      ].map(({ label, value }) => (
                        <div
                          key={label}
                          style={{
                            background: 'var(--acm-elev)',
                            border: '1px solid var(--acm-border)',
                            borderRadius: 'var(--acm-radius)',
                            padding: '12px 14px',
                            textAlign: 'center',
                          }}
                        >
                          <div
                            style={{ fontSize: 20, fontWeight: 700, color: 'var(--acm-accent)' }}
                          >
                            {value}
                          </div>
                          <div className="label" style={{ marginTop: 4 }}>{label}</div>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </ConfigSection>

            {/* ── Telegram ── */}
            <ConfigSection
              id="section-telegram"
              title={tc.telegram.title}
              subtitle={tc.telegram.subtitle}
              icon={Send}
            >
              {/* Integration row */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '10px 0',
                  marginBottom: 16,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span className="dot dot-idle" />
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--acm-fg-2)' }}>Telegram Bot</div>
                    <div className="mono" style={{ fontSize: 11, color: 'var(--acm-fg-4)' }}>
                      Receive and send messages via Telegram
                    </div>
                  </div>
                </div>
              </div>

              <TelegramSetup value={telegramToken} onChange={setTelegramToken} />

              <div style={{ marginTop: 16 }}>
                <button
                  className="btn-primary"
                  onClick={handleTelegramSave}
                  disabled={!telegramToken.trim() || saveSetup.isPending}
                  style={{ width: '100%', justifyContent: 'center' }}
                >
                  {saveSetup.isPending ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Save size={14} />
                  )}
                  Save Telegram Token
                </button>
              </div>
            </ConfigSection>

            {/* ── Google Services ── */}
            <ConfigSection
              id="section-google"
              title="Google Services"
              subtitle="Gmail · Calendar · Drive · YouTube"
              icon={Globe2}
            >
              {/* Integration rows */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 0, marginBottom: 16 }}>
                {[
                  { label: 'Credentials', ok: !!googleStatus?.credentials_exist },
                  { label: 'Authorized', ok: !!googleStatus?.token_exist },
                ].map(({ label, ok }) => (
                  <div
                    key={label}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '10px 0',
                      borderBottom: '1px solid var(--acm-border)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span className={`dot ${ok ? 'dot-ok' : 'dot-idle'}`} />
                      <span style={{ fontSize: 13, color: 'var(--acm-fg-2)' }}>{label}</span>
                    </div>
                    <span style={{ fontSize: 11, color: ok ? 'var(--acm-ok)' : 'var(--acm-fg-4)' }}>
                      {ok ? 'Connected' : 'Not configured'}
                    </span>
                  </div>
                ))}
              </div>

              {/* Step 1 — credentials */}
              {!googleStatus?.credentials_exist && (
                <>
                  <div
                    style={{
                      padding: '12px 14px',
                      background: 'oklch(0.74 0.06 230 / 0.08)',
                      border: '1px solid oklch(0.74 0.06 230 / 0.2)',
                      borderRadius: 'var(--acm-radius)',
                      marginBottom: 14,
                    }}
                  >
                    <p style={{ fontWeight: 600, fontSize: 12, color: 'var(--acm-info)', marginBottom: 6 }}>
                      Step 1 — Get credentials
                    </p>
                    <ol
                      style={{
                        fontSize: 11,
                        color: 'var(--acm-fg-3)',
                        paddingLeft: 18,
                        lineHeight: 1.8,
                        margin: 0,
                      }}
                    >
                      <li>Google Cloud Console → APIs &amp; Services → Credentials</li>
                      <li>Create OAuth 2.0 credentials (Desktop application)</li>
                      <li>Enable: Gmail, Calendar, Drive, YouTube APIs</li>
                      <li>Download JSON and paste below</li>
                    </ol>
                  </div>
                  <label className="label" style={{ display: 'block', marginBottom: 8 }}>
                    Paste credentials.json content
                  </label>
                  <textarea
                    className="acm-input mono"
                    value={googleCredJson}
                    onChange={(e) => setGoogleCredJson(e.target.value)}
                    placeholder={'{\n  "installed": {\n    "client_id": "...",\n    ...\n  }\n}'}
                    rows={4}
                    style={{ resize: 'none', fontSize: 11, marginBottom: 12 }}
                    spellCheck={false}
                  />
                  <button
                    className="btn-primary"
                    onClick={async () => {
                      if (googleCredJson.trim()) {
                        await saveGoogleCreds.mutateAsync(googleCredJson.trim());
                        setGoogleCredJson('');
                      }
                    }}
                    disabled={!googleCredJson.trim() || saveGoogleCreds.isPending}
                    style={{ width: '100%', justifyContent: 'center' }}
                  >
                    {saveGoogleCreds.isPending ? (
                      <Loader2 size={13} className="animate-spin" />
                    ) : (
                      <Save size={13} />
                    )}
                    Save Credentials
                  </button>
                </>
              )}

              {/* Step 2 — authorize */}
              {googleStatus?.credentials_exist && !googleStatus?.token_exist && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <div
                    style={{
                      padding: '12px 14px',
                      background: 'oklch(0.74 0.06 230 / 0.08)',
                      border: '1px solid oklch(0.74 0.06 230 / 0.2)',
                      borderRadius: 'var(--acm-radius)',
                      fontSize: 11,
                      color: 'var(--acm-fg-3)',
                      lineHeight: 1.6,
                    }}
                  >
                    <p style={{ fontWeight: 600, fontSize: 12, color: 'var(--acm-info)', marginBottom: 4 }}>
                      Step 2 — Authorize OpenACM
                    </p>
                    A new tab will open with Google's login page. Sign in and click{' '}
                    <strong>Allow</strong>. OpenACM will detect authorization automatically.
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      className="btn-primary"
                      onClick={() => startGoogleAuth.mutate()}
                      disabled={startGoogleAuth.isPending}
                      style={{ flex: 1, justifyContent: 'center' }}
                    >
                      {startGoogleAuth.isPending ? (
                        <Loader2 size={13} className="animate-spin" />
                      ) : (
                        <Globe2 size={13} />
                      )}
                      Connect with Google
                    </button>
                    <button
                      className="btn-secondary"
                      onClick={() => deleteGoogleCreds.mutate()}
                      disabled={deleteGoogleCreds.isPending}
                      title="Remove credentials"
                      style={{ color: 'var(--acm-err)', borderColor: 'oklch(0.68 0.13 22 / 0.4)' }}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                  {startGoogleAuth.isSuccess && (
                    <p
                      style={{
                        textAlign: 'center',
                        fontSize: 11,
                        color: 'var(--acm-fg-4)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: 6,
                      }}
                    >
                      <Loader2 size={11} className="animate-spin" />
                      Waiting for authorization...
                    </p>
                  )}
                </div>
              )}

              {/* Connected */}
              {googleStatus?.token_exist && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 12,
                      padding: '12px 14px',
                      background: 'oklch(0.75 0.09 160 / 0.07)',
                      border: '1px solid oklch(0.75 0.09 160 / 0.25)',
                      borderRadius: 'var(--acm-radius)',
                    }}
                  >
                    <CheckCircle size={18} style={{ color: 'var(--acm-ok)', flexShrink: 0 }} />
                    <div style={{ flex: 1 }}>
                      <p style={{ fontSize: 13, fontWeight: 600, color: 'var(--acm-ok)', margin: 0 }}>
                        Connected
                      </p>
                      <p style={{ fontSize: 11, color: 'var(--acm-fg-4)', margin: '2px 0 0' }}>
                        Gmail, Calendar, Drive and YouTube are active
                      </p>
                    </div>
                    <button
                      className="btn-secondary"
                      onClick={() => deleteGoogleCreds.mutate()}
                      disabled={deleteGoogleCreds.isPending}
                      style={{ fontSize: 12, color: 'var(--acm-err)', borderColor: 'oklch(0.68 0.13 22 / 0.4)' }}
                    >
                      <Trash2 size={12} />
                      Disconnect
                    </button>
                  </div>

                  {/* Replace credentials */}
                  <details>
                    <summary
                      style={{
                        fontSize: 11,
                        color: 'var(--acm-fg-4)',
                        cursor: 'pointer',
                        userSelect: 'none',
                      }}
                    >
                      Replace credentials JSON
                    </summary>
                    <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <textarea
                        className="acm-input mono"
                        value={googleCredJson}
                        onChange={(e) => setGoogleCredJson(e.target.value)}
                        placeholder={'{\n  "installed": { "client_id": "...", ... }\n}'}
                        rows={3}
                        style={{ resize: 'none', fontSize: 11 }}
                        spellCheck={false}
                      />
                      <button
                        className="btn-secondary"
                        onClick={async () => {
                          if (googleCredJson.trim()) {
                            await saveGoogleCreds.mutateAsync(googleCredJson.trim());
                            setGoogleCredJson('');
                          }
                        }}
                        disabled={!googleCredJson.trim() || saveGoogleCreds.isPending}
                      >
                        {saveGoogleCreds.isPending ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                        Save
                      </button>
                    </div>
                  </details>
                </div>
              )}
            </ConfigSection>

            {/* ── Google Stitch ── */}
            <ConfigSection
              id="section-stitch"
              title="Google Stitch"
              subtitle="AI-powered UI generation — creates HTML screens from text descriptions"
              icon={Paintbrush}
            >
              {/* Integration row */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '10px 0',
                  borderBottom: '1px solid var(--acm-border)',
                  marginBottom: 16,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span
                    className={`dot ${providerStatus?.stitch_configured ? 'dot-ok' : 'dot-idle'}`}
                  />
                  <div>
                    <div style={{ fontSize: 13, color: 'var(--acm-fg-2)' }}>Stitch API</div>
                    <div className="mono" style={{ fontSize: 11, color: 'var(--acm-fg-4)' }}>
                      stitch.withgoogle.com
                    </div>
                  </div>
                </div>
                <button className="btn-secondary" style={{ fontSize: 12 }}>
                  {providerStatus?.stitch_configured ? 'Manage' : 'Connect'}
                </button>
              </div>

              {!providerStatus?.stitch_configured && (
                <p style={{ fontSize: 11, color: 'var(--acm-fg-4)', marginBottom: 12, lineHeight: 1.6 }}>
                  Get a key at <span className="mono">stitch.withgoogle.com</span> → Profile → Settings → API key → Create key
                </p>
              )}

              <label className="label" style={{ display: 'block', marginBottom: 8 }}>
                {providerStatus?.stitch_configured ? 'Update API key' : 'API key'}
              </label>
              <div style={{ display: 'flex', gap: 8 }}>
                <input
                  type="password"
                  className="acm-input mono"
                  style={{ flex: 1 }}
                  value={stitchKey}
                  onChange={(e) => setStitchKey(e.target.value)}
                  placeholder="Paste your Stitch API key..."
                  onKeyDown={(e) => e.key === 'Enter' && handleStitchSave()}
                />
                <button
                  className="btn-primary"
                  onClick={handleStitchSave}
                  disabled={!stitchKey.trim() || stitchSaving}
                >
                  {stitchSaving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                  Save
                </button>
              </div>
            </ConfigSection>

            {/* ── Security ── */}
            <ConfigSection
              id="section-security"
              title={tc.security.title}
              subtitle="auth · execution modes · debug"
              icon={Shield}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                <InfoRow label="Authentication" value="Bearer Token" />
                <InfoRow
                  label="Whitelisted Commands"
                  value={String(config?.security?.whitelisted_commands?.length || 0)}
                />
                <InfoRow label="Encryption" value="TLS 1.3" />

                {/* Execution mode */}
                <Divider />
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--acm-fg-2)' }}>
                      Execution Mode
                    </div>
                    <p style={{ fontSize: 11, color: 'var(--acm-fg-4)', marginTop: 3 }}>
                      Controls when commands require approval
                    </p>
                  </div>
                  <div
                    style={{
                      display: 'flex',
                      border: '1px solid var(--acm-border)',
                      borderRadius: 'var(--acm-radius)',
                      overflow: 'hidden',
                    }}
                  >
                    {(['confirmation', 'auto', 'yolo'] as const).map((mode) => {
                      const active = (config?.security?.execution_mode || 'confirmation') === mode;
                      const labels: Record<string, string> = {
                        confirmation: 'Confirm',
                        auto: 'Auto',
                        yolo: 'Yolo',
                      };
                      return (
                        <button
                          key={mode}
                          onClick={() => updateExecutionMode(mode)}
                          style={{
                            padding: '6px 12px',
                            fontSize: 12,
                            fontWeight: 600,
                            border: 'none',
                            borderRight: '1px solid var(--acm-border)',
                            cursor: 'pointer',
                            background: active
                              ? mode === 'yolo'
                                ? 'oklch(0.68 0.13 22 / 0.3)'
                                : 'var(--acm-accent)'
                              : 'var(--acm-elev)',
                            color: active
                              ? mode === 'yolo'
                                ? 'var(--acm-err)'
                                : 'oklch(0.18 0.015 80)'
                              : 'var(--acm-fg-3)',
                            transition: 'all 120ms ease',
                          }}
                        >
                          {labels[mode]}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Debug mode */}
                <Divider />
                <div style={{ paddingTop: 4 }}>
                  <ToggleRow
                    label="Debug Mode"
                    description={
                      isVerbose
                        ? 'DEBUG level active — all internal logs visible in console and log file.'
                        : 'Enable to show all DEBUG-level logs (LLM requests, tool internals, events).'
                    }
                    value={isVerbose}
                    onToggle={() => toggleDebugMode(!isVerbose)}
                    badge={
                      isVerbose ? (
                        <span
                          style={{
                            fontSize: 10,
                            fontWeight: 700,
                            letterSpacing: '0.1em',
                            textTransform: 'uppercase',
                            color: 'var(--acm-accent)',
                            border: '1px solid oklch(0.84 0.16 82 / 0.3)',
                            borderRadius: 4,
                            padding: '1px 6px',
                          }}
                        >
                          VERBOSE
                        </span>
                      ) : undefined
                    }
                  />
                </div>
              </div>
            </ConfigSection>

            {/* ── Voice Interface ── */}
            <VoiceConfigSection />

            {/* ── Code Resurrection ── */}
            <ConfigSection
              id="section-resurrection"
              title="Code Resurrection"
              subtitle="Second Code Brain — index old projects for past-solution recall"
              icon={Archive}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {/* Stats */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 16,
                    padding: '10px 14px',
                    background: 'var(--acm-elev)',
                    border: '1px solid var(--acm-border)',
                    borderRadius: 'var(--acm-radius)',
                  }}
                >
                  <span className="dot dot-accent acm-pulse" />
                  <div style={{ fontSize: 13, color: 'var(--acm-fg-3)' }}>Files indexed:</div>
                  <span className="mono" style={{ fontSize: 13, fontWeight: 700, color: 'var(--acm-accent)' }}>
                    {resurrectionIndexed.toLocaleString()}
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--acm-fg-4)', marginLeft: 4 }}>
                    · Indexing runs silently when OpenACM is idle
                  </span>
                </div>

                {/* Privacy warning */}
                <div
                  style={{
                    display: 'flex',
                    gap: 10,
                    padding: '12px 14px',
                    background: 'oklch(0.84 0.16 82 / 0.05)',
                    border: '1px solid oklch(0.84 0.16 82 / 0.2)',
                    borderRadius: 'var(--acm-radius)',
                  }}
                >
                  <AlertTriangle
                    size={13}
                    style={{ flexShrink: 0, marginTop: 2, color: 'var(--acm-warn)' }}
                  />
                  <div style={{ fontSize: 11, color: 'var(--acm-fg-3)', lineHeight: 1.6 }}>
                    <p style={{ margin: '0 0 4px' }}>
                      <strong>.env</strong>, <strong>.pem</strong> and <strong>.key</strong> files are
                      skipped automatically. All other indexed code stays local — but if a snippet gets
                      retrieved during a cloud LLM conversation, it will be included in that prompt.
                    </p>
                    <p style={{ margin: 0, color: 'var(--acm-fg-4)' }}>
                      If old code has hardcoded tokens inside regular source files, those lines could reach
                      the cloud. Use a local model (Ollama) for sensitive repos.
                    </p>
                  </div>
                </div>

                {/* Path list */}
                {resurrectionPaths.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {resurrectionPaths.map((p) => (
                      <div
                        key={p}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          padding: '8px 12px',
                          background: 'var(--acm-elev)',
                          border: '1px solid var(--acm-border)',
                          borderRadius: 6,
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                          <FolderOpen size={13} style={{ color: 'var(--acm-accent)', flexShrink: 0 }} />
                          <span
                            className="mono"
                            style={{
                              fontSize: 12,
                              color: 'var(--acm-fg-2)',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {p}
                          </span>
                        </div>
                        <button
                          onClick={() => handleRemoveResurrectionPath(p)}
                          disabled={resurrectionLoading}
                          title="Remove"
                          style={{
                            marginLeft: 10,
                            padding: 4,
                            color: 'var(--acm-fg-4)',
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            flexShrink: 0,
                          }}
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div
                    style={{
                      textAlign: 'center',
                      padding: '24px 0',
                      color: 'var(--acm-fg-4)',
                      fontSize: 13,
                    }}
                  >
                    No paths configured yet. Add a root folder to start indexing.
                  </div>
                )}

                {/* Add path */}
                <div style={{ display: 'flex', gap: 8 }}>
                  <input
                    type="text"
                    className="acm-input mono"
                    style={{ flex: 1 }}
                    value={newResurrectionPath}
                    onChange={(e) => setNewResurrectionPath(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddResurrectionPath()}
                    placeholder="e.g. D:\UnityProjects or /home/user/repos"
                  />
                  <button
                    className="btn-primary"
                    onClick={handleAddResurrectionPath}
                    disabled={!newResurrectionPath.trim() || resurrectionLoading}
                  >
                    {resurrectionLoading ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
                    Add
                  </button>
                </div>
              </div>
            </ConfigSection>

            {/* ── Raw JSON Config ── */}
            <ConfigSection
              id="section-raw"
              title={tc.fullConfig}
              subtitle="raw · json · advanced"
              icon={Terminal}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <textarea
                  className="mono"
                  value={jsonConfig || (config ? JSON.stringify(config, null, 2) : '{}')}
                  onChange={(e) => setJsonConfig(e.target.value)}
                  rows={14}
                  spellCheck={false}
                  style={{
                    width: '100%',
                    background: 'oklch(0.13 0.006 255)',
                    border: '1px solid var(--acm-border)',
                    borderRadius: 'var(--acm-radius)',
                    color: 'var(--acm-fg-2)',
                    fontSize: 12,
                    lineHeight: 1.6,
                    padding: '12px 14px',
                    resize: 'vertical',
                    outline: 'none',
                    boxSizing: 'border-box',
                  }}
                />
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="btn-secondary" onClick={handleReloadConfig}>
                    <RefreshCw size={13} />
                    Reload
                  </button>
                  <button
                    className="btn-primary"
                    onClick={handleSaveConfig}
                    disabled={isSaving}
                    style={{ flex: 1, justifyContent: 'center' }}
                  >
                    {isSaving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                    Save Changes
                  </button>
                </div>
              </div>
            </ConfigSection>

          </div>
        </div>
      </div>
    </AppLayout>
  );
}
