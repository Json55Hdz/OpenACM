'use client';

import { useState } from 'react';
import { type ProviderDefinition } from '@/lib/providers';
import { translations } from '@/lib/translations';
import {
  ChevronDown,
  ChevronUp,
  CheckCircle,
  Circle,
  ExternalLink,
  Server,
  KeyRound,
} from 'lucide-react';

const t = translations.onboarding.providerSetup;

interface ProviderCardProps {
  provider: ProviderDefinition;
  isConfigured: boolean;
  onKeyChange: (key: string) => void;
  keyValue: string;
  mode?: 'onboarding' | 'config';
}

export function ProviderCard({
  provider,
  isConfigured,
  onKeyChange,
  keyValue,
  mode = 'onboarding',
}: ProviderCardProps) {
  const [expanded, setExpanded] = useState(false);
  const hasPendingKey = keyValue.trim().length > 0;

  const statusBadge = !provider.needsKey ? (
    <span className="flex items-center gap-1.5 text-xs font-medium text-blue-400 bg-blue-500/10 px-2.5 py-1 rounded-full">
      <Server size={12} />
      {t.noKeyNeeded}
    </span>
  ) : hasPendingKey ? (
    <span className="flex items-center gap-1.5 text-xs font-medium text-amber-400 bg-amber-500/10 px-2.5 py-1 rounded-full">
      <KeyRound size={12} />
      Pending save
    </span>
  ) : isConfigured ? (
    <span className="flex items-center gap-1.5 text-xs font-medium text-green-400 bg-green-500/10 px-2.5 py-1 rounded-full">
      <CheckCircle size={12} />
      {t.configured}
    </span>
  ) : (
    <span className="flex items-center gap-1.5 text-xs font-medium text-slate-500 bg-slate-700/50 px-2.5 py-1 rounded-full">
      <Circle size={12} />
      {t.notConfigured}
    </span>
  );

  return (
    <div className={`bg-slate-800/50 rounded-xl border overflow-hidden transition-colors ${
      hasPendingKey ? 'border-amber-500/40' : 'border-slate-700/50'
    }`}>
      <button
        type="button"
        onClick={() => provider.needsKey && setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 text-left hover:bg-slate-800/80 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-slate-700 rounded-lg flex items-center justify-center text-lg font-bold text-slate-300">
            {provider.name[0]}
          </div>
          <div>
            <h4 className="font-medium text-white">{provider.name}</h4>
            <p className="text-xs text-slate-500">{provider.description}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {statusBadge}
          {provider.needsKey && (
            <span className="text-slate-500">
              {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </span>
          )}
        </div>
      </button>

      {expanded && provider.needsKey && (
        <div className="px-4 pb-4 space-y-3">
          <div className="relative">
            <input
              type="password"
              value={keyValue}
              onChange={(e) => onKeyChange(e.target.value)}
              placeholder={t.enterApiKey}
              className={`w-full px-4 py-2.5 bg-slate-900 border rounded-lg text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent ${
                hasPendingKey ? 'border-amber-500/50' : 'border-slate-600'
              }`}
            />
            {hasPendingKey && (
              <CheckCircle size={16} className="absolute right-3 top-1/2 -translate-y-1/2 text-amber-400" />
            )}
          </div>
          {hasPendingKey && (
            <p className="text-xs text-amber-400">
              Key entered — click &quot;Save &amp; Continue&quot; below to apply
            </p>
          )}
          <a
            href={provider.apiKeyUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            <ExternalLink size={12} />
            {t.getApiKey}
          </a>
        </div>
      )}
    </div>
  );
}
