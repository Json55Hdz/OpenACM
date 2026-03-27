'use client';

import { useState } from 'react';
import { PROVIDERS } from '@/lib/providers';
import { ProviderCard } from '@/components/setup/provider-card';
import { useProviderStatus, useSaveSetup } from '@/hooks/use-setup';
import { translations } from '@/lib/translations';
import { Loader2 } from 'lucide-react';
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

  const hasAnyKey = Object.values(keys).some((v) => v.trim().length > 0);
  const hasAnyConfigured = Object.values(configuredProviders).some(Boolean);
  const canProceed = hasAnyKey || hasAnyConfigured;

  const handleSave = async () => {
    // Filter out empty keys
    const toSave: Record<string, string> = {};
    for (const [key, value] of Object.entries(keys)) {
      if (value.trim()) {
        toSave[key] = value.trim();
      }
    }

    if (Object.keys(toSave).length === 0 && mode === 'config') {
      toast.info('No new keys to save');
      return;
    }

    if (Object.keys(toSave).length > 0) {
      await saveSetup.mutateAsync(toSave);
      toast.success(t.saved);
      // Clear local key state after save
      setKeys({});
    }

    onComplete?.();
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

      <div className="pt-2">
        {mode === 'onboarding' && !canProceed && (
          <p className="text-sm text-amber-400 mb-3">{t.atLeastOne}</p>
        )}
        <button
          onClick={handleSave}
          disabled={
            (mode === 'onboarding' && !canProceed) || saveSetup.isPending
          }
          className="w-full flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl font-medium transition-colors"
        >
          {saveSetup.isPending ? (
            <>
              <Loader2 size={18} className="animate-spin" />
              {t.saving}
            </>
          ) : (
            t.saveAndContinue
          )}
        </button>
      </div>
    </div>
  );
}
