'use client';

import { useState } from 'react';
import { useProviderStatus } from '@/hooks/use-setup';
import { getSuggestedModelsForProviders, getProviderById } from '@/lib/providers';
import { translations } from '@/lib/translations';

const t = translations.onboarding.modelSelect;

export interface ModelSelection {
  model: string;
  provider?: string;  // provider id (e.g. "gemini", "openai")
}

interface ModelSelectorProps {
  selectedModel: string;
  onSelect: (selection: ModelSelection) => void;
}

export function ModelSelector({ selectedModel, onSelect }: ModelSelectorProps) {
  const { data: status } = useProviderStatus();
  const [customModel, setCustomModel] = useState('');

  const configuredIds = Object.entries(status?.providers ?? {})
    .filter(([, configured]) => configured)
    .map(([id]) => id);

  const suggestedModels = getSuggestedModelsForProviders(configuredIds);

  const handleCustomChange = (value: string) => {
    setCustomModel(value);
    if (value.trim()) {
      onSelect({ model: value.trim() });
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold text-white">{t.title}</h3>
        <p className="text-sm text-slate-400 mt-1">{t.subtitle}</p>
      </div>

      {suggestedModels.length > 0 && (
        <div className="space-y-2">
          {suggestedModels.map(({ provider, model, providerId }) => (
            <button
              key={`${providerId}-${model}`}
              type="button"
              onClick={() => {
                onSelect({ model, provider: providerId });
                setCustomModel('');
              }}
              className={`w-full flex items-center justify-between p-3 rounded-lg border transition-colors text-left ${
                selectedModel === model && !customModel
                  ? 'border-blue-500 bg-blue-500/10 text-white'
                  : 'border-slate-700 bg-slate-800/50 text-slate-300 hover:border-slate-600'
              }`}
            >
              <span className="font-mono text-sm">{model}</span>
              <span className="text-xs text-slate-500">{provider}</span>
            </button>
          ))}
        </div>
      )}

      <div>
        <label className="block text-xs text-slate-500 mb-1.5">{t.customModel}</label>
        <input
          type="text"
          value={customModel}
          onChange={(e) => handleCustomChange(e.target.value)}
          placeholder={t.customPlaceholder}
          className="w-full px-4 py-2.5 bg-slate-900 border border-slate-600 rounded-lg text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
      </div>
    </div>
  );
}
