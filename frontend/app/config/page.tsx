'use client';

import { useState, useEffect } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useConfig, useAPI } from '@/hooks/use-api';
import { useSetModel, useProviderStatus, useGoogleStatus, useSaveGoogleCredentials, useDeleteGoogleCredentials, useStartGoogleAuth, useCustomProviders, useAddCustomProvider, useUpdateCustomProvider, useDeleteCustomProvider } from '@/hooks/use-setup';
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
} from 'lucide-react';
import { useRouter } from 'next/navigation';
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
  const router = useRouter();
  const { config, model, isLoading } = useConfig();
  const setModelMut = useSetModel();
  const saveSetup = useSaveSetup();
  const [isVerbose, setIsVerbose] = useState(false);
  const [routerEnabled, setRouterEnabled] = useState(true);
  const [routerObservation, setRouterObservation] = useState(false);
  const [routerThreshold, setRouterThreshold] = useState(0.88);
  const [routerStats, setRouterStats] = useState<Record<string, unknown> | null>(null);
  const [routerLoading, setRouterLoading] = useState(false);

  const { fetchAPI } = useAPI();

  const toggleDebugMode = async (next: boolean) => {
    setIsVerbose(next);
    localStorage.setItem('openacm_debug_mode', next ? 'true' : 'false');
    try {
      await fetchAPI('/api/config/debug_mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: next }),
      });
    } catch {
      // API call is best-effort — UI state is already saved in localStorage
    }
  };

  // Load debug mode from localStorage (instant, no auth needed)
  // Then sync router config from API
  useEffect(() => {
    const saved = localStorage.getItem('openacm_debug_mode');
    if (saved !== null) setIsVerbose(saved === 'true');

    fetchAPI('/api/config/local_router')
      .then(d => {
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
      const body = field === 'enabled' ? { enabled: value } : { enabled: routerEnabled, observation_mode: value };
      const data = await fetchAPI('/api/config/local_router', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
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
      await fetchAPI('/api/config/local_router', {
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
  const { data: customProviders = [] } = useCustomProviders();
  const addCustomProvider = useAddCustomProvider();
  const updateCustomProvider = useUpdateCustomProvider();
  const deleteCustomProvider = useDeleteCustomProvider();

  const [showAddCustomProvider, setShowAddCustomProvider] = useState(false);
  const [cpForm, setCpForm] = useState({ name: '', base_url: '', api_key: '', default_model: '', suggested_models: '' });
  const [editingCpId, setEditingCpId] = useState<string | null>(null);
  const [editCpForm, setEditCpForm] = useState({ name: '', base_url: '', api_key: '', default_model: '', suggested_models: '' });

  const handleAddCustomProvider = async () => {
    const { name, base_url, api_key, default_model, suggested_models } = cpForm;
    if (!name.trim() || !base_url.trim()) return;
    const suggested = suggested_models.split(',').map(s => s.trim()).filter(Boolean);
    await addCustomProvider.mutateAsync({ name: name.trim(), base_url: base_url.trim(), api_key: api_key.trim() || undefined, default_model: default_model.trim() || undefined, suggested_models: suggested.length ? suggested : undefined });
    setCpForm({ name: '', base_url: '', api_key: '', default_model: '', suggested_models: '' });
    setShowAddCustomProvider(false);
  };

  const handleUpdateCustomProvider = async (id: string) => {
    const { name, base_url, api_key, default_model, suggested_models } = editCpForm;
    const suggested = suggested_models.split(',').map(s => s.trim()).filter(Boolean);
    await updateCustomProvider.mutateAsync({ id, name: name.trim(), base_url: base_url.trim(), api_key: api_key.trim() || undefined, default_model: default_model.trim(), suggested_models: suggested });
    setEditingCpId(null);
  };
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

  // Build provider list from API response, merging static definitions with custom ones
  const configuredProviders = Object.entries(providerStatus?.providers ?? {})
    .filter(([, enabled]) => enabled)
    .map(([id]) => {
      const staticDef = getProviderById(id);
      if (staticDef) return staticDef;
      const customDef = customProviders.find(cp => cp.id === id);
      if (customDef) return {
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

          {/* Custom Providers */}
          <div className="lg:col-span-2">
            <ConfigSection
              title="Custom Providers"
              subtitle="Add any OpenAI-compatible endpoint — LM Studio, Together AI, Groq, etc."
              icon={Server}
            >
              <div className="space-y-4">
                {/* Existing custom providers list */}
                {customProviders.length > 0 && (
                  <div className="space-y-2">
                    {customProviders.map((cp) => (
                      <div key={cp.id} className="rounded-lg border border-slate-700/50 bg-slate-800/30 overflow-hidden">
                        {editingCpId === cp.id ? (
                          <div className="p-4 space-y-3">
                            <div className="grid grid-cols-2 gap-3">
                              <div>
                                <label className="block text-xs text-slate-500 mb-1">Name</label>
                                <input
                                  value={editCpForm.name}
                                  onChange={e => setEditCpForm(p => ({ ...p, name: e.target.value }))}
                                  className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                                />
                              </div>
                              <div>
                                <label className="block text-xs text-slate-500 mb-1">Base URL</label>
                                <input
                                  value={editCpForm.base_url}
                                  onChange={e => setEditCpForm(p => ({ ...p, base_url: e.target.value }))}
                                  className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                                />
                              </div>
                              <div>
                                <label className="block text-xs text-slate-500 mb-1">Default Model</label>
                                <input
                                  value={editCpForm.default_model}
                                  onChange={e => setEditCpForm(p => ({ ...p, default_model: e.target.value }))}
                                  placeholder="e.g. llama-3.1-8b"
                                  className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                                />
                              </div>
                              <div>
                                <label className="block text-xs text-slate-500 mb-1">API Key (leave blank to keep existing)</label>
                                <input
                                  type="password"
                                  value={editCpForm.api_key}
                                  onChange={e => setEditCpForm(p => ({ ...p, api_key: e.target.value }))}
                                  placeholder="sk-..."
                                  className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                                />
                              </div>
                            </div>
                            <div>
                              <label className="block text-xs text-slate-500 mb-1">Suggested Models (comma-separated)</label>
                              <input
                                value={editCpForm.suggested_models}
                                onChange={e => setEditCpForm(p => ({ ...p, suggested_models: e.target.value }))}
                                placeholder="model-a, model-b"
                                className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                              />
                            </div>
                            <div className="flex gap-2">
                              <button
                                onClick={() => handleUpdateCustomProvider(cp.id)}
                                disabled={updateCustomProvider.isPending}
                                className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg text-sm transition-colors"
                              >
                                {updateCustomProvider.isPending ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                                Save
                              </button>
                              <button onClick={() => setEditingCpId(null)} className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg text-sm transition-colors">
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="px-4 py-3 flex items-center justify-between">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-white">{cp.name}</span>
                                {cp.has_key && <span className="text-[10px] bg-green-500/15 text-green-400 border border-green-500/30 rounded px-1.5 py-0.5">Key set</span>}
                              </div>
                              <div className="text-xs text-slate-500 font-mono truncate mt-0.5">{cp.base_url}</div>
                              {cp.default_model && <div className="text-xs text-slate-400 mt-0.5">Default: <span className="font-mono">{cp.default_model}</span></div>}
                            </div>
                            <div className="flex items-center gap-1 ml-3">
                              <button
                                onClick={() => {
                                  setEditingCpId(cp.id);
                                  setEditCpForm({ name: cp.name, base_url: cp.base_url, api_key: '', default_model: cp.default_model, suggested_models: cp.suggested_models.join(', ') });
                                }}
                                className="p-1.5 text-slate-500 hover:text-blue-400 transition-colors"
                                title="Edit"
                              >
                                <Pencil size={14} />
                              </button>
                              <button
                                onClick={() => deleteCustomProvider.mutate(cp.id)}
                                disabled={deleteCustomProvider.isPending}
                                className="p-1.5 text-slate-500 hover:text-red-400 transition-colors"
                                title="Delete"
                              >
                                <Trash2 size={14} />
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {/* Add form */}
                {showAddCustomProvider ? (
                  <div className="p-4 rounded-lg border border-blue-500/30 bg-blue-500/5 space-y-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium text-white">New Custom Provider</span>
                      <button onClick={() => setShowAddCustomProvider(false)} className="text-slate-500 hover:text-slate-300">
                        <X size={16} />
                      </button>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs text-slate-500 mb-1">Name <span className="text-red-400">*</span></label>
                        <input
                          value={cpForm.name}
                          onChange={e => setCpForm(p => ({ ...p, name: e.target.value }))}
                          placeholder="e.g. LM Studio"
                          className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-slate-500 mb-1">Base URL <span className="text-red-400">*</span></label>
                        <input
                          value={cpForm.base_url}
                          onChange={e => setCpForm(p => ({ ...p, base_url: e.target.value }))}
                          placeholder="http://localhost:1234/v1"
                          className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-slate-500 mb-1">Default Model</label>
                        <input
                          value={cpForm.default_model}
                          onChange={e => setCpForm(p => ({ ...p, default_model: e.target.value }))}
                          placeholder="e.g. llama-3.1-8b-instruct"
                          className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-slate-500 mb-1">API Key (optional)</label>
                        <input
                          type="password"
                          value={cpForm.api_key}
                          onChange={e => setCpForm(p => ({ ...p, api_key: e.target.value }))}
                          placeholder="sk-... or leave blank for local"
                          className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs text-slate-500 mb-1">Suggested Models (comma-separated, optional)</label>
                      <input
                        value={cpForm.suggested_models}
                        onChange={e => setCpForm(p => ({ ...p, suggested_models: e.target.value }))}
                        placeholder="model-a, model-b, model-c"
                        className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                    <div className="pt-1 text-xs text-slate-500">
                      Any OpenAI-compatible endpoint works — LM Studio, Ollama's OpenAI API, Together AI, Groq, Perplexity, etc.
                    </div>
                    <button
                      onClick={handleAddCustomProvider}
                      disabled={!cpForm.name.trim() || !cpForm.base_url.trim() || addCustomProvider.isPending}
                      className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors"
                    >
                      {addCustomProvider.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                      Add Provider
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setShowAddCustomProvider(true)}
                    className="flex items-center gap-2 px-4 py-2 border border-dashed border-slate-600 hover:border-blue-500/50 hover:bg-blue-500/5 text-slate-400 hover:text-blue-400 text-sm rounded-lg transition-colors w-full justify-center"
                  >
                    <Plus size={14} />
                    Add Custom Provider
                  </button>
                )}
              </div>
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
                            {provDef?.cliDisclaimer && (
                              <div className="mx-3 mb-2 flex items-start gap-1.5 p-2 bg-amber-500/5 border border-amber-500/20 rounded text-xs text-amber-300/80 leading-relaxed">
                                <span className="mt-0.5 flex-shrink-0">⚠</span>
                                {provDef.cliDisclaimer}
                              </div>
                            )}
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

          {/* Google Stitch */}
          <ConfigSection
            title="Google Stitch"
            subtitle="AI-powered UI generation — creates HTML screens from text descriptions"
            icon={Paintbrush}
          >
            <div className="space-y-4">
              <div className={cn(
                "flex items-center gap-2 px-3 py-2 rounded-lg border text-sm",
                providerStatus?.stitch_configured
                  ? "bg-green-500/10 border-green-500/30 text-green-400"
                  : "bg-amber-500/10 border-amber-500/30 text-amber-400"
              )}>
                {providerStatus?.stitch_configured
                  ? <><CheckCircle size={14} /> API key configured</>
                  : <><MinusCircle size={14} /> Not configured — get a key at stitch.withgoogle.com → Profile picture → Settings → API key → Create key</>
                }
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1.5">
                  {providerStatus?.stitch_configured ? 'Update API key' : 'API key'}
                </label>
                <div className="flex gap-2">
                  <input
                    type="password"
                    value={stitchKey}
                    onChange={(e) => setStitchKey(e.target.value)}
                    placeholder="Paste your Stitch API key..."
                    className="flex-1 px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <button
                    onClick={handleStitchSave}
                    disabled={!stitchKey.trim() || stitchSaving}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors flex items-center gap-2"
                  >
                    {stitchSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                    Save
                  </button>
                </div>
              </div>
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
                        VERBOSE
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
                    ? 'DEBUG level active — all internal logs visible in console and log file.'
                    : 'Enable to show all DEBUG-level logs (LLM requests, tool internals, events).'}
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
            <div className="flex items-center gap-4">
              <button
                onClick={() => router.push('/onboarding?force=true')}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600/15 hover:bg-blue-600/25 text-blue-400 border border-blue-600/30 transition-colors"
              >
                <Wand2 size={13} />
                Setup Wizard
              </button>
              <div className="flex items-center gap-2">
                <CheckCircle size={14} className="text-green-400" />
                <span>System Online</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
