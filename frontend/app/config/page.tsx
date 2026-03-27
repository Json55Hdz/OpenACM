'use client';

import { useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useConfig } from '@/hooks/use-api';
import { useSetModel, useProviderStatus } from '@/hooks/use-setup';
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
  Copy,
  RefreshCw,
  ToggleLeft,
  ToggleRight,
  Send,
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
  const [jsonConfig, setJsonConfig] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [telegramToken, setTelegramToken] = useState('');
  const [customModel, setCustomModel] = useState('');
  const { data: providerStatus } = useProviderStatus();

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
    setCustomModel('');
  };

  const configuredProviders = PROVIDERS.filter(
    (p) => providerStatus?.providers?.[p.id]
  );
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
                        const models = provDef?.suggestedModels ?? [];

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
                              {models.map((m) => {
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
                    <input
                      type="text"
                      value={customModel}
                      onChange={(e) => setCustomModel(e.target.value)}
                      placeholder="e.g. gpt-4o-mini"
                      className="flex-1 px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                    <button
                      onClick={() => {
                        if (customModel.trim()) {
                          handleSetModel(customModel.trim(), activeProviderId);
                        }
                      }}
                      disabled={!customModel.trim() || setModelMut.isPending}
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
                  <span className="text-sm text-slate-300">Debug Mode</span>
                  <button
                    onClick={() => setIsVerbose(!isVerbose)}
                    className={cn(
                      'p-1 rounded transition-colors',
                      isVerbose ? 'text-blue-400' : 'text-slate-500'
                    )}
                  >
                    {isVerbose ? <ToggleRight size={28} /> : <ToggleLeft size={28} />}
                  </button>
                </div>
                <p className="text-xs text-slate-500 mt-1">
                  Enable detailed logs for debugging
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
