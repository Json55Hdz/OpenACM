export interface ProviderDefinition {
  id: string;
  name: string;
  envVar: string;
  needsKey: boolean;
  isCli?: boolean;
  cliBinary?: string;       // e.g. "claude", "gemini"
  installUrl?: string;      // where to download the CLI
  installCmd?: string;      // e.g. "npm install -g @anthropic-ai/claude-code"
  cliDisclaimer?: string;   // warning shown in setup/config for this CLI provider
  suggestedModels: string[];
  apiKeyUrl: string;
  description: string;
}

export const PROVIDERS: ProviderDefinition[] = [
  {
    id: 'openai',
    name: 'OpenAI',
    envVar: 'OPENAI_API_KEY',
    needsKey: true,
    suggestedModels: ['gpt-4o', 'gpt-4o-mini'],
    apiKeyUrl: 'https://platform.openai.com/api-keys',
    description: 'GPT-4o and GPT-4o-mini models',
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    envVar: 'ANTHROPIC_API_KEY',
    needsKey: true,
    suggestedModels: ['claude-sonnet-4-20250514'],
    apiKeyUrl: 'https://console.anthropic.com/settings/keys',
    description: 'Claude Sonnet and other Claude models',
  },
  {
    id: 'gemini',
    name: 'Google Gemini',
    envVar: 'GEMINI_API_KEY',
    needsKey: true,
    suggestedModels: ['gemini-2.5-flash', 'gemini-2.5-pro'],
    apiKeyUrl: 'https://aistudio.google.com/apikey',
    description: 'Gemini 2.5 Flash and Pro models',
  },
  {
    id: 'openrouter',
    name: 'OpenRouter',
    envVar: 'OPENROUTER_API_KEY',
    needsKey: true,
    suggestedModels: ['auto'],
    apiKeyUrl: 'https://openrouter.ai/keys',
    description: 'Access multiple providers through one API',
  },
  {
    id: 'opencode_go',
    name: 'OpenCode Go',
    envVar: 'OPENCODE_GO_API_KEY',
    needsKey: true,
    suggestedModels: ['kimi-k2.5', 'GLM-4-Flash'],
    apiKeyUrl: 'https://opencode.ai',
    description: 'Kimi, GLM, and MiniMax models',
  },
  {
    id: 'xai',
    name: 'xAI Grok',
    envVar: 'XAI_API_KEY',
    needsKey: true,
    suggestedModels: [
      'grok-4.20-0309-reasoning',
      'grok-4.20-0309-non-reasoning',
      'grok-4-1-fast-reasoning',
      'grok-4-1-fast-non-reasoning',
    ],
    apiKeyUrl: 'https://console.x.ai/',
    description: 'Grok 4 reasoning and non-reasoning models from xAI',
  },
  {
    id: 'ollama',
    name: 'Ollama',
    envVar: '',
    needsKey: false,
    suggestedModels: ['llama3.2'],
    apiKeyUrl: 'https://ollama.com/download',
    description: 'Run models locally (no API key needed)',
  },
  {
    id: 'cli_claude',
    name: 'Claude (CLI)',
    envVar: '',
    needsKey: false,
    isCli: true,
    cliBinary: 'claude',
    installUrl: 'https://claude.ai/download',
    installCmd: 'npm install -g @anthropic-ai/claude-code',
    suggestedModels: ['claude'],
    apiKeyUrl: 'https://claude.ai/download',
    description: 'Use Claude via CLI — no API key, full tool support',
    cliDisclaimer: 'Runs via Claude Code CLI using your account session (no API key needed). ACM tools work via a text-based protocol — slightly less reliable than the official API. Requires the CLI to be logged in; if the session expires you\'ll need to run "claude" to re-authenticate.',
  },
  {
    id: 'cli_gemini',
    name: 'Gemini (CLI)',
    envVar: '',
    needsKey: false,
    isCli: true,
    cliBinary: 'gemini',
    installUrl: 'https://ai.google.dev/gemini-api/docs/gemini-cli',
    installCmd: 'npm install -g @google/gemini-cli',
    suggestedModels: ['gemini'],
    apiKeyUrl: 'https://ai.google.dev/gemini-api/docs/gemini-cli',
    description: 'Use Gemini via CLI — no API key, uses your Google account',
    cliDisclaimer: 'Runs via Gemini CLI using your Google account (no API key needed). ACM tools work via a text-based protocol — may be less reliable than the official API. Requires the CLI to be logged in; run "gemini" to re-authenticate if needed.',
  },
  {
    id: 'cli_opencode',
    name: 'OpenCode (CLI)',
    envVar: '',
    needsKey: false,
    isCli: true,
    cliBinary: 'opencode',
    installUrl: 'https://opencode.ai',
    installCmd: 'npm install -g opencode-ai',
    suggestedModels: ['opencode'],
    apiKeyUrl: 'https://opencode.ai',
    description: 'Use OpenCode via CLI — ideal for code & file tasks',
    cliDisclaimer: "OpenCode runs as its own agent with its own tools (bash, file editing). ACM tools like take_screenshot or browser_agent won't be called — OpenCode handles tasks using its internal capabilities. Best for coding and file-related requests.",
  },
];

export function getProviderById(id: string): ProviderDefinition | undefined {
  return PROVIDERS.find((p) => p.id === id);
}

export function getSuggestedModelsForProviders(configuredIds: string[]): { provider: string; providerId: string; model: string }[] {
  const result: { provider: string; providerId: string; model: string }[] = [];
  for (const id of configuredIds) {
    const provider = getProviderById(id);
    if (provider) {
      for (const model of provider.suggestedModels) {
        result.push({ provider: provider.name, providerId: provider.id, model });
      }
    }
  }
  return result;
}
