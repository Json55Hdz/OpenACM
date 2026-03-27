export interface ProviderDefinition {
  id: string;
  name: string;
  envVar: string;
  needsKey: boolean;
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
    suggestedModels: ['gemini-2.0-flash', 'gemini/gemini-1.5-pro'],
    apiKeyUrl: 'https://aistudio.google.com/apikey',
    description: 'Gemini Flash and Pro models',
  },
  {
    id: 'openrouter',
    name: 'OpenRouter',
    envVar: 'OPENROUTER_API_KEY',
    needsKey: true,
    suggestedModels: ['openrouter/auto'],
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
    id: 'ollama',
    name: 'Ollama',
    envVar: '',
    needsKey: false,
    suggestedModels: ['llama3.2'],
    apiKeyUrl: 'https://ollama.com/download',
    description: 'Run models locally (no API key needed)',
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
