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
  AlertCircle,
  Terminal,
} from 'lucide-react';

const t = translations.onboarding.providerSetup;

interface OllamaStatus {
  running: boolean;
  models: string[];
}

interface CliStatus {
  available: boolean;
}

interface ProviderCardProps {
  provider: ProviderDefinition;
  isConfigured: boolean;
  onKeyChange: (key: string) => void;
  keyValue: string;
  mode?: 'onboarding' | 'config';
  ollamaStatus?: OllamaStatus | null;
  cliStatus?: CliStatus | null;
}

// Badge styles using design tokens
function Badge({ color, bg, border, icon: Icon, label }: {
  color: string; bg: string; border: string;
  icon: React.ElementType; label: string;
}) {
  return (
    <span
      className="flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full"
      style={{ color, background: bg, border: `1px solid ${border}` }}
    >
      <Icon size={12} />
      {label}
    </span>
  );
}

export function ProviderCard({
  provider,
  isConfigured,
  onKeyChange,
  keyValue,
  mode = 'onboarding',
  ollamaStatus,
  cliStatus,
}: ProviderCardProps) {
  const [expanded, setExpanded] = useState(false);
  const hasPendingKey = keyValue.trim().length > 0;

  const isOllama = provider.id === 'ollama';
  const isCli = provider.isCli === true;
  const ollamaLoaded = ollamaStatus != null;
  const ollamaRunning = ollamaStatus?.running ?? false;
  const cliLoaded = cliStatus != null;
  const cliAvailable = cliStatus?.available ?? false;
  const isExpandable = provider.needsKey || (isOllama && ollamaLoaded) || (isCli && cliLoaded);

  const statusBadge = !provider.needsKey ? (
    isCli && cliLoaded ? (
      cliAvailable ? (
        <Badge color="var(--acm-ok)" bg="oklch(0.75 0.09 160 / 0.1)" border="oklch(0.75 0.09 160 / 0.25)" icon={CheckCircle} label="Installed" />
      ) : (
        <Badge color="var(--acm-warn)" bg="oklch(0.82 0.1 78 / 0.1)" border="oklch(0.82 0.1 78 / 0.25)" icon={AlertCircle} label="Not installed" />
      )
    ) : isOllama && ollamaLoaded ? (
      ollamaRunning ? (
        <Badge color="var(--acm-ok)" bg="oklch(0.75 0.09 160 / 0.1)" border="oklch(0.75 0.09 160 / 0.25)" icon={CheckCircle} label="Running" />
      ) : (
        <Badge color="var(--acm-err)" bg="oklch(0.68 0.13 22 / 0.1)" border="oklch(0.68 0.13 22 / 0.25)" icon={AlertCircle} label="Not installed" />
      )
    ) : (
      <Badge color="var(--acm-fg-3)" bg="var(--acm-elev)" border="var(--acm-border)" icon={Server} label={t.noKeyNeeded} />
    )
  ) : hasPendingKey ? (
    <Badge color="var(--acm-warn)" bg="oklch(0.82 0.1 78 / 0.1)" border="oklch(0.82 0.1 78 / 0.25)" icon={KeyRound} label="Pending save" />
  ) : isConfigured ? (
    <Badge color="var(--acm-ok)" bg="oklch(0.75 0.09 160 / 0.1)" border="oklch(0.75 0.09 160 / 0.25)" icon={CheckCircle} label={t.configured} />
  ) : (
    <Badge color="var(--acm-fg-4)" bg="var(--acm-elev)" border="var(--acm-border)" icon={Circle} label={t.notConfigured} />
  );

  const cardBorder = hasPendingKey
    ? 'oklch(0.82 0.1 78 / 0.4)'
    : (isOllama && ollamaLoaded && !ollamaRunning) || (isCli && cliLoaded && !cliAvailable)
    ? 'oklch(0.82 0.1 78 / 0.2)'
    : 'var(--acm-border)';

  return (
    <div
      className="rounded-xl overflow-hidden transition-colors"
      style={{
        background: 'var(--acm-elev)',
        border: `1px solid ${cardBorder}`,
      }}
    >
      <button
        type="button"
        onClick={() => isExpandable && setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 text-left transition-colors"
        style={{ cursor: isExpandable ? 'pointer' : 'default' }}
        onMouseEnter={(e) => { if (isExpandable) (e.currentTarget as HTMLButtonElement).style.background = 'oklch(0.25 0.007 255 / 0.8)'; }}
        onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = ''; }}
      >
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center text-lg font-bold"
            style={{ background: 'var(--acm-card)', color: 'var(--acm-fg-2)' }}
          >
            {provider.name[0]}
          </div>
          <div>
            <h4 className="font-medium" style={{ color: 'var(--acm-fg)' }}>{provider.name}</h4>
            <p className="text-xs" style={{ color: 'var(--acm-fg-4)' }}>{provider.description}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {statusBadge}
          {isExpandable && (
            <span style={{ color: 'var(--acm-fg-4)' }}>
              {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </span>
          )}
        </div>
      </button>

      {expanded && provider.needsKey && (
        <div
          className="px-4 pb-4 space-y-3"
          style={{ borderTop: '1px solid var(--acm-border)' }}
        >
          <div className="relative pt-3">
            <input
              type="password"
              value={keyValue}
              onChange={(e) => onKeyChange(e.target.value)}
              placeholder={t.enterApiKey}
              className="acm-input mono"
              style={{
                borderBottomColor: hasPendingKey ? 'var(--acm-warn)' : undefined,
              }}
            />
            {hasPendingKey && (
              <CheckCircle
                size={16}
                className="absolute right-0 top-1/2 translate-y-0.5"
                style={{ color: 'var(--acm-warn)' }}
              />
            )}
          </div>
          {hasPendingKey && (
            <p className="text-xs" style={{ color: 'var(--acm-warn)' }}>
              Key entered — click &quot;Save &amp; Continue&quot; below to apply
            </p>
          )}
          <a
            href={provider.apiKeyUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-xs transition-colors"
            style={{ color: 'var(--acm-accent)' }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = 'var(--acm-accent-hi)'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = 'var(--acm-accent)'; }}
          >
            <ExternalLink size={12} />
            {t.getApiKey}
          </a>
        </div>
      )}

      {expanded && isCli && cliLoaded && (
        <div
          className="px-4 pb-4 space-y-3 pt-3"
          style={{ borderTop: '1px solid var(--acm-border)' }}
        >
          {provider.cliDisclaimer && (
            <div
              className="flex items-start gap-2 p-2.5 rounded-lg"
              style={{
                background: 'oklch(0.82 0.1 78 / 0.05)',
                border: '1px solid oklch(0.82 0.1 78 / 0.2)',
              }}
            >
              <AlertCircle size={13} className="mt-0.5 flex-shrink-0" style={{ color: 'var(--acm-warn)' }} />
              <p className="text-xs leading-relaxed" style={{ color: 'var(--acm-warn)', opacity: 0.8 }}>
                {provider.cliDisclaimer}
              </p>
            </div>
          )}
          {cliAvailable ? (
            <div className="space-y-1">
              <p className="text-xs font-medium flex items-center gap-1.5" style={{ color: 'var(--acm-ok)' }}>
                <Terminal size={12} />
                <code className="font-mono">{provider.cliBinary}</code> is installed and ready.
              </p>
              <p className="text-xs" style={{ color: 'var(--acm-fg-3)' }}>
                Make sure you are logged in:{' '}
                <code
                  className="px-1.5 py-0.5 rounded mono"
                  style={{ color: 'var(--acm-fg-2)', background: 'var(--acm-card)' }}
                >
                  {provider.cliBinary} --help
                </code>
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-xs" style={{ color: 'var(--acm-fg-3)' }}>
                <code style={{ color: 'var(--acm-fg-2)' }}>{provider.cliBinary}</code> is not installed or not on PATH.
              </p>
              <ol className="text-xs space-y-1.5 list-decimal list-inside" style={{ color: 'var(--acm-fg-3)' }}>
                {provider.installCmd && (
                  <li>
                    Install:{' '}
                    <code
                      className="px-1.5 py-0.5 rounded mono"
                      style={{ color: 'var(--acm-fg-2)', background: 'var(--acm-card)' }}
                    >
                      {provider.installCmd}
                    </code>
                  </li>
                )}
                <li>
                  Log in and verify with{' '}
                  <code
                    className="px-1 py-0.5 rounded mono"
                    style={{ color: 'var(--acm-fg-2)', background: 'var(--acm-card)' }}
                  >
                    {provider.cliBinary} --help
                  </code>
                </li>
                <li>Refresh this page — it will appear as Installed</li>
              </ol>
              {provider.installUrl && (
                <a
                  href={provider.installUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-xs transition-colors"
                  style={{ color: 'var(--acm-accent)' }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = 'var(--acm-accent-hi)'; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = 'var(--acm-accent)'; }}
                >
                  <ExternalLink size={12} />
                  Installation guide
                </a>
              )}
            </div>
          )}
        </div>
      )}

      {expanded && isOllama && ollamaLoaded && (
        <div
          className="px-4 pb-4 space-y-3 pt-3"
          style={{ borderTop: '1px solid var(--acm-border)' }}
        >
          {ollamaRunning ? (
            <>
              <p className="text-xs font-medium" style={{ color: 'var(--acm-fg-3)' }}>
                Installed models:
              </p>
              {ollamaStatus!.models.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {ollamaStatus!.models.map((m) => (
                    <span
                      key={m}
                      className="text-xs px-2 py-0.5 rounded mono"
                      style={{ background: 'var(--acm-card)', color: 'var(--acm-fg-2)', border: '1px solid var(--acm-border)' }}
                    >
                      {m}
                    </span>
                  ))}
                </div>
              ) : (
                <div className="space-y-1">
                  <p className="text-xs" style={{ color: 'var(--acm-warn)' }}>No models downloaded yet.</p>
                  <p className="text-xs" style={{ color: 'var(--acm-fg-4)' }}>
                    Run in terminal:{' '}
                    <code
                      className="px-1.5 py-0.5 rounded mono"
                      style={{ color: 'var(--acm-fg-2)', background: 'var(--acm-card)' }}
                    >
                      ollama pull llama3.2
                    </code>
                  </p>
                </div>
              )}
            </>
          ) : (
            <div className="space-y-2">
              <p className="text-xs" style={{ color: 'var(--acm-fg-3)' }}>
                Ollama is not installed or not running.
              </p>
              <ol className="text-xs space-y-1.5 list-decimal list-inside" style={{ color: 'var(--acm-fg-3)' }}>
                <li>
                  Download from{' '}
                  <a
                    href="https://ollama.com/download"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-0.5 transition-colors"
                    style={{ color: 'var(--acm-accent)' }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = 'var(--acm-accent-hi)'; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = 'var(--acm-accent)'; }}
                  >
                    ollama.com/download <ExternalLink size={10} />
                  </a>
                </li>
                <li>Install and launch the app</li>
                <li>
                  Download a model:{' '}
                  <code
                    className="px-1.5 py-0.5 rounded mono"
                    style={{ color: 'var(--acm-fg-2)', background: 'var(--acm-card)' }}
                  >
                    ollama pull llama3.2
                  </code>
                </li>
                <li>Refresh this page — Ollama will appear as Running</li>
              </ol>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
