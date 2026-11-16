import type React from 'react';
import { Route, Bot, Brain, Globe2, Mic, Send, Server, Settings, Shield, Smartphone, Terminal, Zap } from 'lucide-react';

export type NavSection =
  | 'assistant'
  | 'providers'
  | 'custom-providers'
  | 'model'
  | 'routes'
  | 'memory'
  | 'telegram'
  | 'whatsapp'
  | 'google'
  | 'router'
  | 'security'
  | 'voice'
  | 'raw';

export const NAV_GROUPS: { group: string; items: { id: NavSection; label: string; icon: React.ElementType }[] }[] = [
  {
    group: 'AI',
    items: [
      { id: 'assistant', label: 'Assistant Identity', icon: Bot },
      { id: 'providers', label: 'LLM Providers', icon: Settings },
      { id: 'custom-providers', label: 'Custom Providers', icon: Server },
      { id: 'model', label: 'Default Model', icon: Bot },
      { id: 'routes', label: 'Models per task', icon: Route },
      { id: 'memory', label: 'Memory & RAG', icon: Brain },
      { id: 'router', label: 'Intent Router', icon: Zap },
    ],
  },
  {
    group: 'Integrations',
    items: [
      { id: 'telegram', label: 'Telegram', icon: Send },
      { id: 'whatsapp', label: 'WhatsApp', icon: Smartphone },
      { id: 'google', label: 'Google Services', icon: Globe2 },
    ],
  },
  {
    group: 'System',
    items: [
      { id: 'security', label: 'Security', icon: Shield },
      { id: 'voice', label: 'Voice Interface', icon: Mic },
      { id: 'raw', label: 'Raw Config', icon: Terminal },
    ],
  },
];
