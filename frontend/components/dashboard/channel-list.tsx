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
        return (
          <div 
            key={channel.name}
            className="flex items-center justify-between p-3 bg-slate-800/50 rounded-lg"
          >
            <div className="flex items-center gap-3">
              <Icon size={18} className="text-slate-400" />
              <span className="text-slate-200 font-medium">{channel.name}</span>
            </div>
            <span className={`
              px-2 py-1 text-xs font-medium rounded-full
              ${channel.status === 'online' 
                ? 'bg-green-500/20 text-green-400' 
                : 'bg-slate-700 text-slate-400'}
            `}>
              {channel.status === 'online' ? 'Online' : 'Offline'}
            </span>
          </div>
        );
      })}
    </div>
  );
}
