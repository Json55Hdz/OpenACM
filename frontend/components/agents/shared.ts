import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import type { AgentFormData } from '@/hooks/use-agents';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const TOOLS_OPTIONS = [
  { value: 'all', label: 'All tools' },
  { value: 'none', label: 'No tools (text only)' },
];

export const DEFAULT_FORM: AgentFormData = {
  name: '',
  description: '',
  system_prompt: '',
  allowed_tools: 'all',
  show_in_chat: true,
  telegram_token: '',
  memory_mode: 'persistent',
  memory_ttl_hours: 24,
  inactivity_timeout_minutes: 0,
  inactivity_message: '',
};
