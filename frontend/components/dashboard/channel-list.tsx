'use client';

import { Monitor, Globe } from 'lucide-react';

const channels = [
  { name: 'Console', icon: Monitor, status: 'online' as const },
  { name: 'Web', icon: Globe, status: 'online' as const },
];

export function ChannelList() {
  return (
    <div className="space-y-3">
      {channels.map((channel) => {
        const Icon = channel.icon;
        const online = channel.status === 'online';
        return (
          <div
            key={channel.name}
            className="flex items-center justify-between p-3 rounded-lg"
            style={{ background: 'var(--acm-elev)', border: '1px solid var(--acm-border)' }}
          >
            <div className="flex items-center gap-3">
              <Icon size={18} style={{ color: 'var(--acm-fg-3)' }} />
              <span className="font-medium" style={{ color: 'var(--acm-fg-2)' }}>
                {channel.name}
              </span>
            </div>
            <span
              className="px-2 py-1 text-xs font-medium rounded-full"
              style={{
                background: online ? 'oklch(0.75 0.09 160 / 0.12)' : 'var(--acm-elev)',
                color: online ? 'var(--acm-ok)' : 'var(--acm-fg-4)',
                border: `1px solid ${online ? 'oklch(0.75 0.09 160 / 0.3)' : 'var(--acm-border)'}`,
              }}
            >
              {online ? 'Online' : 'Offline'}
            </span>
          </div>
        );
      })}
    </div>
  );
}
