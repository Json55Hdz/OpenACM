'use client';

import { useState } from 'react';
import { PROVIDERS } from '@/lib/providers';
import { ProviderCard } from '@/components/setup/provider-card';
import { useProviderStatus, useSaveSetup, useOllamaStatus, useCliStatus } from '@/hooks/use-setup';
import { translations } from '@/lib/translations';
import { Loader2, Save, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';

const t = translations.onboarding.providerSetup;

interface ProviderSetupFormProps {
  mode?: 'onboarding' | 'config';
  onComplete?: () => void;
}

export function ProviderSetupForm({ mode = 'onboarding', onComplete }: ProviderSetupFormProps) {
  const { data: status } = useProviderStatus();
  const { data: ollamaStatus } = useOllamaStatus();
  const { data: cliClaudeStatus } = useCliStatus('claude');
  const { data: cliGeminiStatus } = useCliStatus('gemini');
  const { data: cliOpenCodeStatus } = useCliStatus('opencode');
  const saveSetup = useSaveSetup();

  const cliStatusMap: Record<string, { available: boolean } | null | undefined> = {
    cli_claude:   cliClaudeStatus   ? { available: cliClaudeStatus.available }   : null,
    cli_gemini:   cliGeminiStatus   ? { available: cliGeminiStatus.available }   : null,
    cli_opencode: cliOpenCodeStatus ? { available: cliOpenCodeStatus.available } : null,
  };
  const [keys, setKeys] = useState<Record<string, string>>({});

  const configuredProviders = status?.providers ?? {};

  const handleKeyChange = (providerId: string, envVar: string, value: string) => {
    setKeys((prev) => ({ ...prev, [envVar]: value }));
  };

  const pendingKeys = Object.entries(keys).filter(([, v]) => v.trim().length > 0);
  const hasAnyConfigured = Object.values(configuredProviders).some(Boolean);
  const canProceed = pendingKeys.length > 0 || hasAnyConfigured;

  const handleSave = async () => {
    const toSave: Record<string, string> = {};
    for (const [key, value] of Object.entries(keys)) {
      if (value.trim()) toSave[key] = value.trim();
    }

    if (Object.keys(toSave).length === 0) {
      if (mode === 'config') {
        toast.info('No new keys to save');
        return;
      }
      if (hasAnyConfigured) {
        onComplete?.();
        return;
      }
      return;
    }

    try {
      await saveSetup.mutateAsync(toSave);
      toast.success(t.saved);
      setKeys({});
      onComplete?.();
    } catch {
      // Error toast handled by the hook
    }
  };

  return (
    <div className="space-y-4">
      {mode === 'onboarding' && (
        <div className="mb-2">
          <h2 className="text-xl font-bold" style={{ color: 'var(--acm-fg)' }}>{t.title}</h2>
          <p className="text-sm mt-1" style={{ color: 'var(--acm-fg-3)' }}>{t.subtitle}</p>
        </div>
      )}

      <div className="space-y-3">
        {PROVIDERS.map((provider) => (
          <ProviderCard
            key={provider.id}
            provider={provider}
            isConfigured={configuredProviders[provider.id] ?? false}
            keyValue={keys[provider.envVar] ?? ''}
            onKeyChange={(val) => handleKeyChange(provider.id, provider.envVar, val)}
            mode={mode}
            ollamaStatus={provider.id === 'ollama' ? (ollamaStatus ?? null) : undefined}
            cliStatus={provider.isCli ? (cliStatusMap[provider.id] ?? null) : undefined}
          />
        ))}
      </div>

      {/* Privacy notice */}
      <div
        className="flex items-start gap-2.5 p-3 rounded-lg"
        style={{
          background: 'oklch(0.75 0.09 160 / 0.06)',
          border: '1px solid oklch(0.75 0.09 160 / 0.2)',
        }}
      >
        <ShieldCheck size={15} className="mt-0.5 flex-shrink-0" style={{ color: 'var(--acm-ok)' }} />
        <p className="text-xs leading-relaxed" style={{ color: 'var(--acm-fg-3)' }}>
          <span style={{ color: 'var(--acm-ok)', fontWeight: 600 }}>Your data stays local.</span>{' '}
          API keys are stored only in your local{' '}
          <code style={{ color: 'var(--acm-fg-2)' }}>.env</code> file.
          OpenACM does not collect, transmit, or share any keys, conversations, or files with third parties.
          All traffic goes directly from your machine to the provider you choose.
        </p>
      </div>

      <div className="pt-2">
        {mode === 'onboarding' && !canProceed && (
          <p className="text-sm mb-3" style={{ color: 'var(--acm-warn)' }}>{t.atLeastOne}</p>
        )}
        {pendingKeys.length > 0 && (
          <p className="text-sm mb-3" style={{ color: 'var(--acm-warn)' }}>
            {pendingKeys.length} key{pendingKeys.length > 1 ? 's' : ''} pending — click below to save
          </p>
        )}

        <button
          onClick={handleSave}
          disabled={(mode === 'onboarding' && !canProceed) || saveSetup.isPending}
          className="btn-primary w-full justify-center"
          style={{ padding: '11px 16px', fontSize: 14 }}
        >
          {saveSetup.isPending ? (
            <>
              <Loader2 size={18} className="animate-spin" />
              {t.saving}
            </>
          ) : pendingKeys.length > 0 ? (
            <>
              <Save size={18} />
              Save {pendingKeys.length} key{pendingKeys.length > 1 ? 's' : ''} &amp; Continue
            </>
          ) : (
            t.saveAndContinue
          )}
        </button>
      </div>
    </div>
  );
}
