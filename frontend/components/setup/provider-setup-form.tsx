'use client';

import { useState } from 'react';
import { PROVIDERS } from '@/lib/providers';
import { ProviderCard } from '@/components/setup/provider-card';
import { useProviderStatus, useSaveSetup } from '@/hooks/use-setup';
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
  const saveSetup = useSaveSetup();
  const [keys, setKeys] = useState<Record<string, string>>({});

  const configuredProviders = status?.providers ?? {};

  const handleKeyChange = (providerId: string, envVar: string, value: string) => {
    setKeys((prev) => ({ ...prev, [envVar]: value }));
  };

  const pendingKeys = Object.entries(keys).filter(([, v]) => v.trim().length > 0);
  const hasAnyConfigured = Object.values(configuredProviders).some(Boolean);
  const canProceed = pendingKeys.length > 0 || hasAnyConfigured;

  const handleSave = async () => {
    // Filter out empty keys
    const toSave: Record<string, string> = {};
    for (const [key, value] of Object.entries(keys)) {
      if (value.trim()) {
        toSave[key] = value.trim();
      }
    }

    if (Object.keys(toSave).length === 0) {
      if (mode === 'config') {
        toast.info('No new keys to save');
        return;
      }
      // In onboarding, if already configured, just proceed
      if (hasAnyConfigured) {
        onComplete?.();
        return;
      }
      return;
    }

    try {
      await saveSetup.mutateAsync(toSave);
      toast.success(t.saved);
      // Clear local key state after save
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
          <h2 className="text-xl font-bold text-white">{t.title}</h2>
          <p className="text-sm text-slate-400 mt-1">{t.subtitle}</p>
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
          />
        ))}
      </div>

      {/* Privacy notice */}
      <div className="flex items-start gap-2.5 p-3 bg-green-500/5 border border-green-500/20 rounded-lg">
        <ShieldCheck size={15} className="text-green-400 mt-0.5 flex-shrink-0" />
        <p className="text-xs text-slate-400 leading-relaxed">
          <span className="text-green-400 font-medium">Your data stays local.</span>{' '}
          API keys are stored only in your local <code className="text-slate-300">.env</code> file.
          OpenACM does not collect, transmit, or share any keys, conversations, or files with third parties.
          All traffic goes directly from your machine to the provider you choose.
        </p>
      </div>

      <div className="pt-2">
        {mode === 'onboarding' && !canProceed && (
          <p className="text-sm text-amber-400 mb-3">{t.atLeastOne}</p>
        )}

        {pendingKeys.length > 0 && (
          <p className="text-sm text-amber-400 mb-3">
            {pendingKeys.length} key{pendingKeys.length > 1 ? 's' : ''} pending — click below to save
          </p>
        )}

        <button
          onClick={handleSave}
          disabled={
            (mode === 'onboarding' && !canProceed) || saveSetup.isPending
          }
          className={`w-full flex items-center justify-center gap-2 px-6 py-3 rounded-xl font-medium transition-colors ${
            pendingKeys.length > 0
              ? 'bg-amber-500 hover:bg-amber-600 text-black'
              : 'bg-blue-600 hover:bg-blue-700 text-white'
          } disabled:opacity-50 disabled:cursor-not-allowed`}
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
