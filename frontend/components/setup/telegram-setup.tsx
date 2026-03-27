'use client';

import { useState } from 'react';
import { useProviderStatus } from '@/hooks/use-setup';
import { translations } from '@/lib/translations';
import { CheckCircle, Circle, ExternalLink } from 'lucide-react';

const t = translations.onboarding.telegramSetup;
const ps = translations.onboarding.providerSetup;

interface TelegramSetupProps {
  value: string;
  onChange: (value: string) => void;
}

export function TelegramSetup({ value, onChange }: TelegramSetupProps) {
  const { data: status } = useProviderStatus();
  const isConfigured = status?.telegram_configured ?? false;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-white">{t.title}</h3>
          <p className="text-sm text-slate-400 mt-1">{t.subtitle}</p>
        </div>
        {isConfigured ? (
          <span className="flex items-center gap-1.5 text-xs font-medium text-green-400 bg-green-500/10 px-2.5 py-1 rounded-full">
            <CheckCircle size={12} />
            {ps.configured}
          </span>
        ) : (
          <span className="flex items-center gap-1.5 text-xs font-medium text-slate-500 bg-slate-700/50 px-2.5 py-1 rounded-full">
            <Circle size={12} />
            {ps.notConfigured}
          </span>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1.5">
          {t.tokenLabel}
        </label>
        <input
          type="password"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={t.tokenPlaceholder}
          className="w-full px-4 py-2.5 bg-slate-900 border border-slate-600 rounded-lg text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
      </div>

      <a
        href="https://t.me/BotFather"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
      >
        <ExternalLink size={12} />
        {t.howToGet}
      </a>
    </div>
  );
}
