'use client';

import { useState } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useConfig } from '@/hooks/use-api';
import { useDashboardStore } from '@/stores/dashboard-store';
import { 
  Settings, 
  Bot, 
  Shield, 
  MessageSquare, 
  Terminal,
  Save,
  Loader2,
  CheckCircle,
  Copy,
  RefreshCw,
  ToggleLeft,
  ToggleRight,
  Smartphone,
  Globe,
  Monitor
} from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { toast } from 'sonner';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

interface Channel {
  id: string;
  name: string;
  type: 'console' | 'web' | 'mobile';
  status: 'online' | 'offline';
  messages_today: number;
}

function ConfigSection({ 
  title, 
  icon: Icon, 
  children 
}: { 
  title: string; 
  icon: React.ElementType; 
  children: React.ReactNode 
}) {
  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-800 bg-slate-800/30">
        <div className="flex items-center gap-3">
          <Icon size={20} className="text-blue-400" />
          <h3 className="font-semibold text-white">{title}</h3>
        </div>
      </div>
      <div className="p-6">
        {children}
      </div>
    </div>
  );
}

function InfoRow({ label, value, copyable = false }: { label: string; value: string; copyable?: boolean }) {
  const handleCopy = () => {
    navigator.clipboard.writeText(value);
    toast.success('Copied to clipboard');
  };
  
  return (
    <div className="flex items-center justify-between py-3 border-b border-slate-800 last:border-b-0">
      <span className="text-sm text-slate-400">{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-sm text-slate-200 font-mono">{value}</span>
        {copyable && (
          <button
            onClick={handleCopy}
            className="p-1 text-slate-500 hover:text-blue-400 transition-colors"
          >
            <Copy size={14} />
          </button>
        )}
      </div>
    </div>
  );
}

function ChannelCard({ channel }: { channel: Channel }) {
  const icons = {
    console: Monitor,
    web: Globe,
    mobile: Smartphone,
  };
  
  const Icon = icons[channel.type];
  
  return (
    <div className="flex items-center justify-between p-4 bg-slate-800/50 rounded-lg">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 bg-slate-800 rounded-lg flex items-center justify-center">
          <Icon size={20} className="text-slate-400" />
        </div>
        <div>
          <p className="font-medium text-slate-200">{channel.name}</p>
          <p className="text-xs text-slate-500 capitalize">{channel.type}</p>
        </div>
      </div>
      <div className="flex items-center gap-4">
        <div className="text-right">
          <p className="text-sm font-medium text-slate-300">{channel.messages_today}</p>
          <p className="text-xs text-slate-500">messages today</p>
        </div>
        <span className={cn(
          "px-2 py-1 text-xs font-medium rounded-full",
          channel.status === 'online' 
            ? "bg-green-500/20 text-green-400" 
            : "bg-slate-700 text-slate-400"
        )}>
          {channel.status === 'online' ? 'Online' : 'Offline'}
        </span>
      </div>
    </div>
  );
}

export default function ConfigPage() {
  const { config, model, isLoading, updateModel } = useConfig();
  const stats = useDashboardStore((state) => state.stats);
  const [isVerbose, setIsVerbose] = useState(false);
  const [jsonConfig, setJsonConfig] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  
  // Mock channels data
  const channels: Channel[] = [
    { id: 'console', name: 'Console', type: 'console', status: 'online', messages_today: 12 },
    { id: 'web', name: 'Web Chat', type: 'web', status: 'online', messages_today: 45 },
  ];
  
  // Initialize JSON config when data loads
  useState(() => {
    if (config) {
      setJsonConfig(JSON.stringify(config, null, 2));
    }
  });
  
  const handleSaveConfig = async () => {
    setIsSaving(true);
    try {
      // Parse and validate JSON
      const parsed = JSON.parse(jsonConfig);
      // Here you would send to API
      toast.success('Configuration saved successfully');
    } catch (e) {
      toast.error('Invalid JSON. Check the syntax.');
    } finally {
      setIsSaving(false);
    }
  };
  
  const handleReloadConfig = () => {
    if (config) {
      setJsonConfig(JSON.stringify(config, null, 2));
      toast.success('Configuration reloaded');
    }
  };
  
  return (
    <AppLayout>
      <div className="p-6 lg:p-8">
        {/* Header */}
        <header className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-white">Configuration</h1>
              <p className="text-slate-400 mt-1">Manage the system configuration</p>
            </div>
          </div>
        </header>
        
        {/* Config Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Model Info */}
          <ConfigSection title="LLM Model" icon={Bot}>
            {isLoading ? (
              <div className="space-y-3">
                <div className="h-10 bg-slate-800 rounded animate-pulse" />
                <div className="h-10 bg-slate-800 rounded animate-pulse" />
              </div>
            ) : (
              <div className="space-y-4">
                <InfoRow
                  label="Current Model"
                  value={model?.model || stats.currentModel || 'Not configured'}
                  copyable
                />
                <InfoRow
                  label="Provider"
                  value={model?.provider || 'OpenRouter'}
                />
                <InfoRow
                  label="Status"
                  value={model?.status || 'Active'}
                />
                
                <div className="pt-4 border-t border-slate-800">
                  <label className="block text-sm font-medium text-slate-300 mb-2">
                    Change Model
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      placeholder="openai/gpt-4o"
                      className="flex-1 px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
                    />
                    <button
                      onClick={() => {
                        const input = document.querySelector('input[placeholder="openai/gpt-4o"]') as HTMLInputElement;
                        if (input?.value) {
                          updateModel(input.value);
                        }
                      }}
                      className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
                    >
                      <RefreshCw size={16} />
                      Change
                    </button>
                  </div>
                </div>
              </div>
            )}
          </ConfigSection>
          
          {/* Security */}
          <ConfigSection title="Security" icon={Shield}>
            <div className="space-y-4">
              <InfoRow
                label="Authentication"
                value="Bearer Token"
              />
              <InfoRow
                label="Token Expiration"
                value="24 hours"
              />
              <InfoRow
                label="Rate Limit"
                value="100 req/min"
              />
              <InfoRow
                label="Encryption"
                value="TLS 1.3"
              />
              
              <div className="pt-4 border-t border-slate-800">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-300">Debug Mode</span>
                  <button
                    onClick={() => setIsVerbose(!isVerbose)}
                    className={cn(
                      "p-1 rounded transition-colors",
                      isVerbose ? "text-blue-400" : "text-slate-500"
                    )}
                  >
                    {isVerbose ? <ToggleRight size={28} /> : <ToggleLeft size={28} />}
                  </button>
                </div>
                <p className="text-xs text-slate-500 mt-1">
                  Enable detailed logs for debugging
                </p>
              </div>
            </div>
          </ConfigSection>
          
          {/* Channels */}
          <ConfigSection title="Channels" icon={MessageSquare}>
            <div className="space-y-3">
              {channels.map((channel) => (
                <ChannelCard key={channel.id} channel={channel} />
              ))}
            </div>
            
            <div className="mt-4 pt-4 border-t border-slate-800">
              <button className="w-full flex items-center justify-center gap-2 px-4 py-2 border border-dashed border-slate-700 text-slate-500 rounded-lg hover:border-slate-500 hover:text-slate-400 transition-colors">
                <RefreshCw size={16} />
                <span>Sync Channels</span>
              </button>
            </div>
          </ConfigSection>
          
          {/* JSON Config */}
          <ConfigSection title="JSON Configuration" icon={Terminal}>
            <div className="space-y-4">
              <div className="relative">
                <textarea
                  value={jsonConfig || (config ? JSON.stringify(config, null, 2) : '{}')}
                  onChange={(e) => setJsonConfig(e.target.value)}
                  rows={12}
                  className="w-full px-4 py-3 bg-slate-950 border border-slate-800 rounded-lg text-slate-300 font-mono text-sm focus:outline-none focus:border-blue-500 resize-none"
                  spellCheck={false}
                />
              </div>
              
              <div className="flex gap-2">
                <button
                  onClick={handleReloadConfig}
                  className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition-colors"
                >
                  <RefreshCw size={16} />
                  Reload
                </button>
                <button
                  onClick={handleSaveConfig}
                  disabled={isSaving}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg transition-colors"
                >
                  {isSaving ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Save size={16} />
                  )}
                  Save Changes
                </button>
              </div>
            </div>
          </ConfigSection>
        </div>
        
        {/* System Info Footer */}
        <div className="mt-8 p-4 bg-slate-900 rounded-xl border border-slate-800">
          <div className="flex flex-wrap items-center justify-between gap-4 text-sm text-slate-500">
            <div className="flex items-center gap-4">
              <span>OpenACM v0.1.0</span>
              <span>•</span>
              <span>Next.js 15</span>
              <span>•</span>
              <span>React 19</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle size={14} className="text-green-400" />
              <span>System Online</span>
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
