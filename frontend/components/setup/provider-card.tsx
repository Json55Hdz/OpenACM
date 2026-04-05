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
        <span className="flex items-center gap-1.5 text-xs font-medium text-green-400 bg-green-500/10 px-2.5 py-1 rounded-full">
          <CheckCircle size={12} />
          Installed
        </span>
      ) : (
        <span className="flex items-center gap-1.5 text-xs font-medium text-amber-400 bg-amber-500/10 px-2.5 py-1 rounded-full">
          <AlertCircle size={12} />
          Not installed
        </span>
      )
    ) : isOllama && ollamaLoaded ? (
      ollamaRunning ? (
        <span className="flex items-center gap-1.5 text-xs font-medium text-green-400 bg-green-500/10 px-2.5 py-1 rounded-full">
          <CheckCircle size={12} />
          Running
        </span>
      ) : (
        <span className="flex items-center gap-1.5 text-xs font-medium text-red-400 bg-red-500/10 px-2.5 py-1 rounded-full">
          <AlertCircle size={12} />
          Not installed
        </span>
      )
    ) : (
      <span className="flex items-center gap-1.5 text-xs font-medium text-blue-400 bg-blue-500/10 px-2.5 py-1 rounded-full">
        <Server size={12} />
        {t.noKeyNeeded}
      </span>
    )
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

  const borderColor = hasPendingKey
    ? 'border-amber-500/40'
    : (isOllama && ollamaLoaded && !ollamaRunning) || (isCli && cliLoaded && !cliAvailable)
    ? 'border-amber-500/20'
    : 'border-slate-700/50';

  return (
    <div className={`bg-slate-800/50 rounded-xl border overflow-hidden transition-colors ${borderColor}`}>
      <button
        type="button"
        onClick={() => isExpandable && setExpanded(!expanded)}
        className={`w-full flex items-center justify-between p-4 text-left transition-colors ${
          isExpandable ? 'hover:bg-slate-800/80 cursor-pointer' : 'cursor-default'
        }`}
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
          {isExpandable && (
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

      {expanded && isCli && cliLoaded && (
        <div className="px-4 pb-4 space-y-3 border-t border-slate-700/50 pt-3">
          {provider.cliDisclaimer && (
            <div className="flex items-start gap-2 p-2.5 bg-amber-500/5 border border-amber-500/20 rounded-lg">
              <AlertCircle size={13} className="text-amber-400 mt-0.5 flex-shrink-0" />
              <p className="text-xs text-amber-300/80 leading-relaxed">{provider.cliDisclaimer}</p>
            </div>
          )}
          {cliAvailable ? (
            <div className="space-y-1">
              <p className="text-xs text-green-400 font-medium flex items-center gap-1.5">
                <Terminal size={12} />
                <code className="font-mono">{provider.cliBinary}</code> is installed and ready.
              </p>
              <p className="text-xs text-slate-400">
                Make sure you are logged in:{' '}
                <code className="text-slate-300 bg-slate-900 px-1.5 py-0.5 rounded">
                  {provider.cliBinary} --help
                </code>
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-slate-400">
                <code className="text-slate-300">{provider.cliBinary}</code> is not installed or not on PATH.
              </p>
              <ol className="text-xs text-slate-400 space-y-1.5 list-decimal list-inside">
                {provider.installCmd && (
                  <li>
                    Install:{' '}
                    <code className="text-slate-300 bg-slate-900 px-1.5 py-0.5 rounded">
                      {provider.installCmd}
                    </code>
                  </li>
                )}
                <li>Log in and verify with <code className="text-slate-300 bg-slate-900 px-1 py-0.5 rounded">{provider.cliBinary} --help</code></li>
                <li>Refresh this page — it will appear as Installed</li>
              </ol>
              {provider.installUrl && (
                <a
                  href={provider.installUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
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
        <div className="px-4 pb-4 space-y-3 border-t border-slate-700/50 pt-3">
          {ollamaRunning ? (
            <>
              <p className="text-xs text-slate-400 font-medium">Installed models:</p>
              {ollamaStatus!.models.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {ollamaStatus!.models.map((m) => (
                    <span key={m} className="text-xs bg-slate-700 text-slate-300 px-2 py-0.5 rounded font-mono">
                      {m}
                    </span>
                  ))}
                </div>
              ) : (
                <div className="space-y-1">
                  <p className="text-xs text-amber-400">No models downloaded yet.</p>
                  <p className="text-xs text-slate-500">
                    Run in terminal:{' '}
                    <code className="text-slate-300 bg-slate-900 px-1.5 py-0.5 rounded">ollama pull llama3.2</code>
                  </p>
                </div>
              )}
            </>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-slate-400">Ollama is not installed or not running.</p>
              <ol className="text-xs text-slate-400 space-y-1.5 list-decimal list-inside">
                <li>
                  Download from{' '}
                  <a
                    href="https://ollama.com/download"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-400 hover:text-blue-300 inline-flex items-center gap-0.5"
                  >
                    ollama.com/download <ExternalLink size={10} />
                  </a>
                </li>
                <li>Install and launch the app</li>
                <li>
                  Download a model:{' '}
                  <code className="text-slate-300 bg-slate-900 px-1.5 py-0.5 rounded">ollama pull llama3.2</code>
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
