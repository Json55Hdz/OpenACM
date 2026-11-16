import type React from 'react';
import { Layers, LifeBuoy, Route, Bot, Brain, Globe2, Mic, Send, Server, Settings, Shield, Smartphone, Terminal, Zap } from 'lucide-react';

export type NavSection =
  | 'assistant'
  | 'providers'
  | 'custom-providers'
  | 'model'
  | 'routes'
  | 'fallbacks'
  | 'models-overview'
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
      { id: 'memory', label: 'Memory & RAG', icon: Brain },
      { id: 'router', label: 'Intent Router', icon: Zap },
    ],
  },
  {
    group: 'Modelos',
    items: [
      { id: 'models-overview', label: 'Resumen', icon: Layers },
      { id: 'providers', label: 'A · Conectar proveedores', icon: Settings },
      { id: 'custom-providers', label: 'B · Proveedores propios', icon: Server },
      { id: 'model', label: 'C · Modelo principal', icon: Bot },
      { id: 'routes', label: 'D · Modelos por tarea', icon: Route },
      { id: 'fallbacks', label: 'E · Respaldo si falla', icon: LifeBuoy },
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
