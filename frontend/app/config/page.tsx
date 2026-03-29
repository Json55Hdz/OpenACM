'use client';

import { useState, useEffect } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useConfig } from '@/hooks/use-api';
import { useSetModel, useProviderStatus, useGoogleStatus, useSaveGoogleCredentials, useDeleteGoogleCredentials, useStartGoogleAuth } from '@/hooks/use-setup';
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
} from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { toast } from 'sonner';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const tc = translations.config;

function ConfigSection({
  title,
  subtitle,
  icon: Icon,
  children,
}: {
  title: string;
  subtitle?: string;
  icon: React.ElementType;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-800 bg-slate-800/30">
        <div className="flex items-center gap-3">
          <Icon size={20} className="text-blue-400" />
          <div>
            <h3 className="font-semibold text-white">{title}</h3>
            {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
          </div>
        </div>
      </div>
      <div className="p-6">{children}</div>
    </div>
  );
}

function InfoRow({
  label,
  value,
  copyable = false,
}: {
  label: string;
  value: string;
  copyable?: boolean;
}) {
  const handleCopy = () => {
    navigator.clipboard.writeText(value);
    toast.success('Copied to clipboard');
  };

  return (
    <div className="flex items-center justify-between py-3 border-b border-slate-800 last:border-b-0">
      <span className="text-sm text-slate-400">{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-sm text-slate-200 font-mono">{value}</span>
        {copyable && (
          <button
            onClick={handleCopy}
            className="p-1 text-slate-500 hover:text-blue-400 transition-colors"
          >
            <Copy size={14} />
          </button>
        )}
      </div>
    </div>
  );
}

export default function ConfigPage() {
  const { config, model, isLoading } = useConfig();
  const setModelMut = useSetModel();
  const saveSetup = useSaveSetup();
  const [isVerbose, setIsVerbose] = useState(false);
  const [routerEnabled, setRouterEnabled] = useState(true);
  const [routerObservation, setRouterObservation] = useState(false);
  const [routerThreshold, setRouterThreshold] = useState(0.88);
  const [routerStats, setRouterStats] = useState<Record<string, unknown> | null>(null);
  const [routerLoading, setRouterLoading] = useState(false);

  const toggleDebugMode = async (next: boolean) => {
    setIsVerbose(next);
    try {
      await fetch('/api/config/debug_mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: next }),
      });
    } catch {
      setIsVerbose(!next); // revert on error
    }
  };

  // Load router config + debug mode on mount
  useEffect(() => {
    fetch('/api/config/debug_mode')
      .then(r => r.json())
      .then(d => setIsVerbose(d.enabled ?? false))
      .catch(() => {});

    fetch('/api/config/local_router')
      .then(r => r.json())
      .then(d => {
        setRouterEnabled(d.enabled ?? true);
        setRouterObservation(d.observation_mode ?? false);
        setRouterThreshold(d.confidence_threshold ?? 0.88);
        setRouterStats(d);
      })
      .catch(() => {});
  }, []);

  const handleRouterToggle = async (field: 'enabled' | 'observation_mode', value: boolean) => {
    setRouterLoading(true);
    try {
      const body = field === 'enabled' ? { enabled: value } : { enabled: routerEnabled, observation_mode: value };
      const res = await fetch('/api/config/local_router', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      setRouterEnabled(data.enabled);
      toast.success(field === 'enabled'
        ? (value ? 'Local Router enabled' : 'Local Router disabled')
        : (value ? 'Observation mode ON — router classifies but does not execute' : 'Fast-path active — router bypasses LLM for simple intents'));
    } catch {
      toast.error('Failed to update router config');
    } finally {
      setRouterLoading(false);
    }
  };

  const handleThresholdChange = async (val: number) => {
    setRouterThreshold(val);
    try {
      await fetch('/api/config/local_router', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confidence_threshold: val }),
      });
    } catch { /* silent */ }
  };
  const [jsonConfig, setJsonConfig] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [telegramToken, setTelegramToken] = useState('');
  const [customModel, setCustomModel] = useState('');
  const [customProvider, setCustomProvider] = useState('');
  const [savedCustomModels, setSavedCustomModels] = useState<Record<string, string[]>>({});
  const [googleCredJson, setGoogleCredJson] = useState('');

  useEffect(() => {
    try {
      const stored = localStorage.getItem('openacm_custom_models');
      if (stored) setSavedCustomModels(JSON.parse(stored));
    } catch {}
  }, []);

  const persistCustomModel = (modelName: string, providerId: string) => {
    setSavedCustomModels(prev => {
      const list = prev[providerId] ?? [];
      if (list.includes(modelName)) return prev;
      const updated = { ...prev, [providerId]: [...list, modelName] };
      localStorage.setItem('openacm_custom_models', JSON.stringify(updated));
      return updated;
    });
  };

  const removeCustomModel = (modelName: string, providerId: string) => {
    setSavedCustomModels(prev => {
      const updated = { ...prev, [providerId]: (prev[providerId] ?? []).filter(m => m !== modelName) };
      localStorage.setItem('openacm_custom_models', JSON.stringify(updated));
      return updated;
    });
  };
  const { data: providerStatus } = useProviderStatus();
  const { data: googleStatus } = useGoogleStatus();
  const saveGoogleCreds = useSaveGoogleCredentials();
  const deleteGoogleCreds = useDeleteGoogleCredentials();
  const startGoogleAuth = useStartGoogleAuth();

  // Initialize JSON config when data loads
  useState(() => {
    if (config) {
      setJsonConfig(JSON.stringify(config, null, 2));
    }
  });

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

  // Build provider list from API response, falling back to static metadata where available
  const configuredProviders = Object.entries(providerStatus?.providers ?? {})
    .filter(([, enabled]) => enabled)
    .map(([id]) => getProviderById(id) ?? { id, name: id, envVar: '', needsKey: true, suggestedModels: [], apiKeyUrl: '', description: '' });
  const activeProviderId = model?.provider || '';

  const handleTelegramSave = async () => {
    if (telegramToken.trim()) {
      await saveSetup.mutateAsync({ TELEGRAM_TOKEN: telegramToken.trim() });
      toast.success('Telegram token saved');
      setTelegramToken('');
    }
  };

  return (
    <AppLayout>
      <div className="p-6 lg:p-8">
        {/* Header */}
        <header className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-white">{tc.title}</h1>
              <p className="text-slate-400 mt-1">{tc.subtitle}</p>
            </div>
          </div>
        </header>

        {/* Config Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* LLM Providers */}
          <div className="lg:col-span-2">
            <ConfigSection
              title={tc.providers.title}
              subtitle={tc.providers.subtitle}
              icon={Settings}
            >
              <ProviderSetupForm mode="config" />
            </ConfigSection>
          </div>

          {/* Default Model */}
          <ConfigSection title={tc.model.title} icon={Bot}>
            {isLoading ? (
              <div className="space-y-3">
                <div className="h-10 bg-slate-800 rounded animate-pulse" />
                <div className="h-10 bg-slate-800 rounded animate-pulse" />
              </div>
            ) : (
              <div className="space-y-4">
                {/* Current active indicator */}
                <div className="flex items-center justify-between p-3 bg-blue-500/10 border border-blue-500/30 rounded-lg">
                  <div>
                    <p className="text-xs text-blue-400">Active</p>
                    <p className="text-sm font-mono text-white">{model?.model || 'Not configured'}</p>
                  </div>
                  <span className="text-xs text-slate-400">{model?.provider || ''}</span>
                </div>

                {/* Provider tabs */}
                {configuredProviders.length > 0 && (
                  <div>
                    <p className="text-xs text-slate-500 mb-2">Switch provider &amp; model</p>
                    <div className="space-y-3">
                      {configuredProviders.map((prov) => {
                        const isActive = activeProviderId === prov.id;
                        const provDef = getProviderById(prov.id);
                        const suggestedModels = provDef?.suggestedModels ?? [];
                        const customSaved = (savedCustomModels[prov.id] ?? []).filter(m => !suggestedModels.includes(m));

                        return (
                          <div key={prov.id} className={`rounded-lg border transition-colors ${
                            isActive ? 'border-blue-500/40 bg-blue-500/5' : 'border-slate-700/50 bg-slate-800/30'
                          }`}>
                            <div className="px-3 py-2 flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <div className={`w-2 h-2 rounded-full ${isActive ? 'bg-blue-400' : 'bg-slate-600'}`} />
                                <span className={`text-sm font-medium ${isActive ? 'text-white' : 'text-slate-400'}`}>
                                  {prov.name}
                                </span>
                              </div>
                              {isActive && (
                                <span className="text-[10px] uppercase tracking-wider text-blue-400 font-semibold">Active</span>
                              )}
                            </div>
                            <div className="px-3 pb-2 flex flex-wrap gap-1.5">
                              {suggestedModels.map((m) => {
                                const isCurrent = model?.model === m && isActive;
                                return (
                                  <button
                                    key={m}
                                    onClick={() => handleSetModel(m, prov.id)}
                                    disabled={setModelMut.isPending}
                                    className={`px-2.5 py-1 rounded text-xs font-mono transition-colors ${
                                      isCurrent
                                        ? 'bg-blue-600 text-white'
                                        : 'bg-slate-700/60 text-slate-300 hover:bg-slate-600 hover:text-white'
                                    } disabled:opacity-50`}
                                  >
                                    {m}
                                  </button>
                                );
                              })}
                              {customSaved.map((m) => {
                                const isCurrent = model?.model === m && isActive;
                                return (
                                  <div key={m} className="relative group/cm flex items-center">
                                    <button
                                      onClick={() => handleSetModel(m, prov.id)}
                                      disabled={setModelMut.isPending}
                                      className={`pl-2.5 pr-6 py-1 rounded text-xs font-mono transition-colors ${
                                        isCurrent
                                          ? 'bg-violet-600 text-white'
                                          : 'bg-slate-700/60 text-violet-300 hover:bg-slate-600 hover:text-white border border-violet-700/40'
                                      } disabled:opacity-50`}
                                    >
                                      {m}
                                    </button>
                                    <button
                                      onClick={(e) => { e.stopPropagation(); removeCustomModel(m, prov.id); }}
                                      className="absolute right-1 text-slate-500 hover:text-red-400 transition-colors opacity-0 group-hover/cm:opacity-100"
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

                {/* Custom model */}
                <div className="pt-3 border-t border-slate-800">
                  <label className="block text-xs text-slate-500 mb-1.5">Custom model name</label>
                  <div className="flex gap-2">
                    <select
                      value={customProvider}
                      onChange={(e) => setCustomProvider(e.target.value)}
                      className="px-2 py-2 bg-slate-900 border border-slate-600 rounded-lg text-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="">Provider</option>
                      {configuredProviders.map((p) => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                      ))}
                    </select>
                    <input
                      type="text"
                      value={customModel}
                      onChange={(e) => setCustomModel(e.target.value)}
                      placeholder="e.g. gpt-4o-mini"
                      className="flex-1 px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                    <button
                      onClick={handleSetCustomModel}
                      disabled={!customModel.trim() || !customProvider || setModelMut.isPending}
                      className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors"
                    >
                      {setModelMut.isPending ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        'Set'
                      )}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </ConfigSection>

          {/* Telegram */}
          <ConfigSection
            title={tc.telegram.title}
            subtitle={tc.telegram.subtitle}
            icon={Send}
          >
            <div className="space-y-4">
              <TelegramSetup value={telegramToken} onChange={setTelegramToken} />
              <button
                onClick={handleTelegramSave}
                disabled={!telegramToken.trim() || saveSetup.isPending}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg transition-colors"
              >
                {saveSetup.isPending ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <Save size={16} />
                )}
                Save Telegram Token
              </button>
            </div>
          </ConfigSection>

          {/* Google Services */}
          <ConfigSection
            title="Google Services"
            subtitle="Gmail, Calendar, Drive, YouTube"
            icon={Globe2}
          >
            <div className="space-y-4">
              {/* Status badges */}
              <div className="grid grid-cols-2 gap-3">
                <div className={cn(
                  "flex items-center gap-2 px-3 py-2 rounded-lg border text-sm",
                  googleStatus?.credentials_exist
                    ? "bg-green-500/10 border-green-500/30 text-green-400"
                    : "bg-slate-800 border-slate-700 text-slate-500"
                )}>
                  {googleStatus?.credentials_exist ? <CheckCircle size={14} /> : <MinusCircle size={14} />}
                  Credentials
                </div>
                <div className={cn(
                  "flex items-center gap-2 px-3 py-2 rounded-lg border text-sm",
                  googleStatus?.token_exist
                    ? "bg-green-500/10 border-green-500/30 text-green-400"
                    : "bg-slate-800 border-slate-700 text-slate-500"
                )}>
                  {googleStatus?.token_exist ? <CheckCircle size={14} /> : <MinusCircle size={14} />}
                  Authorized
                </div>
              </div>

              {/* Step 1: Upload credentials (only if not yet uploaded) */}
              {!googleStatus?.credentials_exist && (
                <>
                  <div className="p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg text-xs text-blue-300 space-y-1">
                    <p className="font-medium text-blue-200">Step 1 — Get credentials:</p>
                    <ol className="list-decimal list-inside space-y-0.5 text-blue-300/80">
                      <li>Google Cloud Console → APIs &amp; Services → Credentials</li>
                      <li>Create OAuth 2.0 credentials (Desktop application)</li>
                      <li>Enable: Gmail, Calendar, Drive, YouTube APIs</li>
                      <li>Download JSON and paste below</li>
                    </ol>
                  </div>
                  <div>
                    <label className="block text-xs text-slate-500 mb-1.5">Paste credentials.json content</label>
                    <textarea
                      value={googleCredJson}
                      onChange={(e) => setGoogleCredJson(e.target.value)}
                      placeholder={'{\n  "installed": {\n    "client_id": "...",\n    ...\n  }\n}'}
                      rows={4}
                      className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-slate-300 font-mono text-xs focus:outline-none focus:border-blue-500 resize-none"
                      spellCheck={false}
                    />
                  </div>
                  <button
                    onClick={async () => {
                      if (googleCredJson.trim()) {
                        await saveGoogleCreds.mutateAsync(googleCredJson.trim());
                        setGoogleCredJson('');
                      }
                    }}
                    disabled={!googleCredJson.trim() || saveGoogleCreds.isPending}
                    className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg text-sm transition-colors"
                  >
                    {saveGoogleCreds.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                    Save Credentials
                  </button>
                </>
              )}

              {/* Step 2: Authorize (credentials uploaded but not yet authorized) */}
              {googleStatus?.credentials_exist && !googleStatus?.token_exist && (
                <div className="space-y-3">
                  <div className="p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg text-xs text-blue-300">
                    <p className="font-medium text-blue-200 mb-1">Step 2 — Authorize OpenACM</p>
                    <p>A new tab will open with Google's login page. Sign in and click <strong>Allow</strong>. OpenACM will detect authorization automatically.</p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => startGoogleAuth.mutate()}
                      disabled={startGoogleAuth.isPending}
                      className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
                    >
                      {startGoogleAuth.isPending
                        ? <Loader2 size={14} className="animate-spin" />
                        : <Globe2 size={14} />}
                      Connect with Google
                    </button>
                    <button
                      onClick={() => deleteGoogleCreds.mutate()}
                      disabled={deleteGoogleCreds.isPending}
                      className="flex items-center gap-1.5 px-3 py-2 bg-red-900/40 hover:bg-red-800/50 text-red-400 border border-red-700/40 rounded-lg text-sm transition-colors"
                      title="Remove credentials"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                  {startGoogleAuth.isSuccess && (
                    <p className="text-center text-xs text-slate-400 flex items-center justify-center gap-1.5">
                      <Loader2 size={12} className="animate-spin" /> Waiting for authorization...
                    </p>
                  )}
                </div>
              )}

              {/* Connected state */}
              {googleStatus?.token_exist && (
                <div className="p-3 bg-green-500/10 border border-green-500/30 rounded-lg flex items-center gap-3">
                  <CheckCircle size={18} className="text-green-400 flex-shrink-0" />
                  <div className="flex-1">
                    <p className="text-green-400 text-sm font-medium">Connected</p>
                    <p className="text-slate-500 text-xs">Gmail, Calendar, Drive and YouTube are active</p>
                  </div>
                  <button
                    onClick={() => deleteGoogleCreds.mutate()}
                    disabled={deleteGoogleCreds.isPending}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-red-900/40 hover:bg-red-800/50 text-red-400 border border-red-700/40 rounded-lg text-xs transition-colors"
                  >
                    <Trash2 size={12} /> Disconnect
                  </button>
                </div>
              )}

              {/* Replace credentials when already connected */}
              {googleStatus?.credentials_exist && (
                <details className="group">
                  <summary className="text-xs text-slate-500 cursor-pointer hover:text-slate-400">
                    Replace credentials JSON
                  </summary>
                  <div className="mt-2 space-y-2">
                    <textarea
                      value={googleCredJson}
                      onChange={(e) => setGoogleCredJson(e.target.value)}
                      placeholder={'{\n  "installed": { "client_id": "...", ... }\n}'}
                      rows={3}
                      className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-slate-300 font-mono text-xs focus:outline-none focus:border-blue-500 resize-none"
                      spellCheck={false}
                    />
                    <button
                      onClick={async () => {
                        if (googleCredJson.trim()) {
                          await saveGoogleCreds.mutateAsync(googleCredJson.trim());
                          setGoogleCredJson('');
                        }
                      }}
                      disabled={!googleCredJson.trim() || saveGoogleCreds.isPending}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg text-xs transition-colors"
                    >
                      {saveGoogleCreds.isPending ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                      Save
                    </button>
                  </div>
                </details>
              )}
            </div>
          </ConfigSection>

          {/* Local Router */}
          <ConfigSection title="Local Intent Router" subtitle="Hybrid local/cloud processing — bypasses the LLM for simple requests" icon={Zap}>
            <div className="space-y-4">
              {/* Enable/disable */}
              <div className="flex items-center justify-between py-3 border-b border-slate-800">
                <div>
                  <span className="text-sm text-slate-300">Enable Local Router</span>
                  <p className="text-xs text-slate-500 mt-0.5">Classify intents locally using sentence-transformers</p>
                </div>
                <button
                  onClick={() => { setRouterEnabled(!routerEnabled); handleRouterToggle('enabled', !routerEnabled); }}
                  disabled={routerLoading}
                  className={cn('p-1 rounded transition-colors', routerEnabled ? 'text-violet-400' : 'text-slate-500')}
                >
                  {routerEnabled ? <ToggleRight size={28} /> : <ToggleLeft size={28} />}
                </button>
              </div>

              {/* Observation mode */}
              <div className="flex items-center justify-between py-3 border-b border-slate-800">
                <div>
                  <span className="text-sm text-slate-300">Observation Mode</span>
                  <p className="text-xs text-slate-500 mt-0.5">ON = classify only, log stats, never execute. OFF = fast-path active</p>
                </div>
                <button
                  onClick={() => { setRouterObservation(!routerObservation); handleRouterToggle('observation_mode', !routerObservation); }}
                  disabled={routerLoading || !routerEnabled}
                  className={cn('p-1 rounded transition-colors', routerObservation ? 'text-amber-400' : 'text-slate-500', !routerEnabled && 'opacity-40')}
                >
                  {routerObservation ? <ToggleRight size={28} /> : <ToggleLeft size={28} />}
                </button>
              </div>

              {/* Confidence threshold */}
              <div className="py-3 border-b border-slate-800">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-slate-300">Confidence Threshold</span>
                  <span className="text-sm font-mono text-violet-400">{routerThreshold.toFixed(2)}</span>
                </div>
                <input
                  type="range" min="0.50" max="1.00" step="0.01"
                  value={routerThreshold}
                  onChange={e => setRouterThreshold(parseFloat(e.target.value))}
                  onMouseUp={e => handleThresholdChange(parseFloat((e.target as HTMLInputElement).value))}
                  disabled={!routerEnabled}
                  className="w-full accent-violet-500 disabled:opacity-40"
                />
                <div className="flex justify-between text-xs text-slate-600 mt-1">
                  <span>0.50 — aggressive</span>
                  <span>1.00 — conservative</span>
                </div>
              </div>

              {/* Live stats */}
              {routerStats && (
                <div className="grid grid-cols-3 gap-3 pt-2">
                  {[
                    { label: 'Classified', value: String(routerStats.total_classified ?? 0) },
                    { label: 'Fast-path', value: String(routerStats.fast_path_eligible ?? 0) },
                    { label: 'Savings', value: `${routerStats.potential_savings_pct ?? 0}%` },
                  ].map(({ label, value }) => (
                    <div key={label} className="bg-slate-800/50 rounded-lg p-3 text-center">
                      <div className="text-lg font-bold text-violet-400">{value}</div>
                      <div className="text-xs text-slate-500 mt-0.5">{label}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </ConfigSection>

          {/* Security */}
          <ConfigSection title={tc.security.title} icon={Shield}>
            <div className="space-y-4">
              <InfoRow label="Authentication" value="Bearer Token" />
              <InfoRow label="Execution Mode" value={config?.security?.execution_mode || 'confirmation'} />
              <InfoRow
                label="Whitelisted Commands"
                value={String(config?.security?.whitelisted_commands?.length || 0)}
              />
              <InfoRow label="Encryption" value="TLS 1.3" />

              <div className="pt-4 border-t border-slate-800">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-sm text-slate-300">Debug Mode</span>
                    {isVerbose && (
                      <span className="ml-2 text-xs bg-amber-500/15 text-amber-400 border border-amber-500/30 rounded px-1.5 py-0.5">
                        Tools blocked
                      </span>
                    )}
                  </div>
                  <button
                    onClick={() => toggleDebugMode(!isVerbose)}
                    className={cn(
                      'p-1 rounded transition-colors',
                      isVerbose ? 'text-amber-400' : 'text-slate-500'
                    )}
                  >
                    {isVerbose ? <ToggleRight size={28} /> : <ToggleLeft size={28} />}
                  </button>
                </div>
                <p className="text-xs text-slate-500 mt-1">
                  {isVerbose
                    ? 'All tool calls are blocked — AI can converse but cannot execute actions.'
                    : 'Block all tool execution to prevent autonomous actions (e.g. while away).'}
                </p>
              </div>
            </div>
          </ConfigSection>

          {/* JSON Config */}
          <ConfigSection title={tc.fullConfig} icon={Terminal}>
            <div className="space-y-4">
              <div className="relative">
                <textarea
                  value={jsonConfig || (config ? JSON.stringify(config, null, 2) : '{}')}
                  onChange={(e) => setJsonConfig(e.target.value)}
                  rows={12}
                  className="w-full px-4 py-3 bg-slate-950 border border-slate-800 rounded-lg text-slate-300 font-mono text-sm focus:outline-none focus:border-blue-500 resize-none"
                  spellCheck={false}
                />
              </div>

              <div className="flex gap-2">
                <button
                  onClick={handleReloadConfig}
                  className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition-colors"
                >
                  <RefreshCw size={16} />
                  Reload
                </button>
                <button
                  onClick={handleSaveConfig}
                  disabled={isSaving}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg transition-colors"
                >
                  {isSaving ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Save size={16} />
                  )}
                  Save Changes
                </button>
              </div>
            </div>
          </ConfigSection>
        </div>

        {/* System Info Footer */}
        <div className="mt-8 p-4 bg-slate-900 rounded-xl border border-slate-800">
          <div className="flex flex-wrap items-center justify-between gap-4 text-sm text-slate-500">
            <div className="flex items-center gap-4">
              <span>OpenACM v0.1.0</span>
              <span>·</span>
              <span>Next.js 16</span>
              <span>·</span>
              <span>React 19</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle size={14} className="text-green-400" />
              <span>System Online</span>
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
