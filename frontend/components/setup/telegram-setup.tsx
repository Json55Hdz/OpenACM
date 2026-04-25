'use client';

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
          <h3 className="text-lg font-semibold" style={{ color: 'var(--acm-fg)' }}>{t.title}</h3>
          <p className="text-sm mt-1" style={{ color: 'var(--acm-fg-3)' }}>{t.subtitle}</p>
        </div>
        {isConfigured ? (
          <span
            className="flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full"
            style={{
              color: 'var(--acm-ok)',
              background: 'oklch(0.75 0.09 160 / 0.1)',
              border: '1px solid oklch(0.75 0.09 160 / 0.25)',
            }}
          >
            <CheckCircle size={12} />
            {ps.configured}
          </span>
        ) : (
          <span
            className="flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full"
            style={{
              color: 'var(--acm-fg-4)',
              background: 'var(--acm-elev)',
              border: '1px solid var(--acm-border)',
            }}
          >
            <Circle size={12} />
            {ps.notConfigured}
          </span>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium mb-1.5" style={{ color: 'var(--acm-fg-2)' }}>
          {t.tokenLabel}
        </label>
        <input
          type="password"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={t.tokenPlaceholder}
          className="acm-input mono"
        />
      </div>

      <a
        href="https://t.me/BotFather"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1.5 text-xs transition-colors"
        style={{ color: 'var(--acm-accent)' }}
        onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = 'var(--acm-accent-hi)'; }}
        onMouseLeave={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = 'var(--acm-accent)'; }}
      >
        <ExternalLink size={12} />
        {t.howToGet}
      </a>
    </div>
  );
}
