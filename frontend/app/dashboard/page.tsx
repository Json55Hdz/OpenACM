'use client';

import { useEffect } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useStats, useActivityHistory, useMediaFiles } from '@/hooks/use-api';
import { useDashboardStore } from '@/stores/dashboard-store';
import { ActivityChart } from '@/components/dashboard/activity-chart';
import { StatsCard } from '@/components/dashboard/stats-card';
import { ChannelList } from '@/components/dashboard/channel-list';
import { EventLog } from '@/components/dashboard/event-log';
import { MessageSquare, Hash, Wrench, Radio, Download, FileImage, File, Box } from 'lucide-react';
import { useAuthStore } from '@/stores/auth-store';

function fileIcon(ext: string) {
  if (['.png', '.jpg', '.jpeg', '.gif', '.webp'].includes(ext)) return <FileImage size={16} className="text-blue-400" />;
  if (['.glb', '.gltf', '.obj', '.stl', '.blend'].includes(ext)) return <Box size={16} className="text-purple-400" />;
  return <File size={16} className="text-slate-400" />;
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DashboardPage() {
  const { data: stats, isLoading: statsLoading } = useStats();
  const { data: history, isLoading: historyLoading } = useActivityHistory();
  const { data: mediaFiles } = useMediaFiles();
  const { setStats, setOnline } = useDashboardStore();
  const token = useAuthStore((s) => s.token);
  
  useEffect(() => {
    if (stats) {
      setStats({
        messagesToday: stats.messages_today || 0,
        tokensToday: stats.tokens_today || 0,
        toolCalls: stats.total_tool_calls || 0,
        activeConversations: stats.active_conversations || 0,
        currentModel: stats.current_model || 'Unknown',
      });
      setOnline(true);
    }
  }, [stats, setStats, setOnline]);
  
  return (
    <AppLayout>
      <div className="p-6 lg:p-8">
        {/* Header */}
        <header className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-white">Dashboard</h1>
              <p className="text-slate-400 mt-1">Activity monitor and system status</p>
            </div>
            
            <div className="flex items-center gap-2 px-4 py-2 bg-slate-900 rounded-full border border-slate-700">
              <span className="text-xl">🤖</span>
              <span className="text-slate-300 text-sm font-medium">
                {stats?.current_model || 'Loading...'}
              </span>
            </div>
          </div>
        </header>
        
        {/* Stats Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <StatsCard
            icon={<MessageSquare size={24} className="text-blue-400" />}
            value={stats?.messages_today || 0}
            label="Messages Today"
            loading={statsLoading}
          />
          <StatsCard
            icon={<Hash size={24} className="text-purple-400" />}
            value={stats?.tokens_today || 0}
            label="Tokens Today"
            loading={statsLoading}
            formatter={(v) => v >= 1000 ? `${(v/1000).toFixed(1)}K` : String(v)}
          />
          <StatsCard
            icon={<Wrench size={24} className="text-amber-400" />}
            value={stats?.total_tool_calls || 0}
            label="Tool Calls"
            loading={statsLoading}
          />
          <StatsCard
            icon={<Radio size={24} className="text-green-400" />}
            value={stats?.active_conversations || 0}
            label="Conversations"
            loading={statsLoading}
          />
        </div>
        
        {/* Dashboard Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Activity Chart */}
          <div className="lg:col-span-2 bg-slate-900 rounded-xl border border-slate-800 p-6">
            <h3 className="text-lg font-semibold text-white mb-4">Recent Activity</h3>
            <ActivityChart data={history || []} loading={historyLoading} />
          </div>
          
          {/* Channels */}
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
            <h3 className="text-lg font-semibold text-white mb-4">Channels</h3>
            <ChannelList />
          </div>
          
          {/* Event Log */}
          <div className="lg:col-span-3 bg-slate-900 rounded-xl border border-slate-800 p-6">
            <h3 className="text-lg font-semibold text-white mb-4">Live Events</h3>
            <EventLog />
          </div>

          {/* File Browser */}
          <div className="lg:col-span-3 bg-slate-900 rounded-xl border border-slate-800 p-6">
            <h3 className="text-lg font-semibold text-white mb-4">
              Files
              <span className="ml-2 text-sm font-normal text-slate-500">({mediaFiles?.length ?? 0})</span>
            </h3>
            {!mediaFiles || mediaFiles.length === 0 ? (
              <p className="text-slate-500 text-sm">No files yet. Files generated by tools (screenshots, 3D models, etc.) will appear here.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-500 border-b border-slate-800">
                      <th className="pb-2 pr-4 font-medium">File</th>
                      <th className="pb-2 pr-4 font-medium">Size</th>
                      <th className="pb-2 pr-4 font-medium">Modified</th>
                      <th className="pb-2 font-medium"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {mediaFiles.map((f) => (
                      <tr key={f.name} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                        <td className="py-2 pr-4">
                          <div className="flex items-center gap-2">
                            {fileIcon(f.ext)}
                            <span className="text-slate-300 font-mono text-xs truncate max-w-xs">{f.name}</span>
                          </div>
                        </td>
                        <td className="py-2 pr-4 text-slate-400">{formatSize(f.size)}</td>
                        <td className="py-2 pr-4 text-slate-400">{new Date(f.modified).toLocaleString()}</td>
                        <td className="py-2">
                          <a
                            href={`/api/media/${f.name}?download=true&token=${token}`}
                            download={f.name}
                            className="flex items-center gap-1 px-3 py-1 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg text-xs transition-colors"
                          >
                            <Download size={12} />
                            Download
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
