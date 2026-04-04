'use client';

import { useEffect } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useStats, useActivityHistory, useMediaFiles } from '@/hooks/use-api';
import { useDashboardStore } from '@/stores/dashboard-store';
import { ActivityChart } from '@/components/dashboard/activity-chart';
import { StatsCard } from '@/components/dashboard/stats-card';
import { ChannelList } from '@/components/dashboard/channel-list';
import { EventLog } from '@/components/dashboard/event-log';
import {
  MessageSquare,
  Hash,
  Wrench,
  Radio,
  Download,
  FileImage,
  File,
  Box,
  Cpu,
  TrendingUp,
  Info,
} from 'lucide-react';
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

function formatTokens(v: number) {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1000) return `${(v / 1000).toFixed(1)}K`;
  return String(v);
}

function SectionHeader({ title, description }: { title: string; description?: string }) {
  return (
    <div className="mb-4">
      <h3 className="text-lg font-semibold text-white">{title}</h3>
      {description && <p className="text-xs text-slate-500 mt-0.5">{description}</p>}
    </div>
  );
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

  const totalTokensAllTime = Math.max(
    stats?.total_tokens || 0,
    stats?.total_requests !== undefined ? 0 : 0, // prefer DB value
  );

  return (
    <AppLayout>
      <div className="p-6 lg:p-8">
        {/* Header */}
        <header className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-white">Dashboard</h1>
              <p className="text-slate-400 mt-1">Real-time activity monitor and usage statistics</p>
            </div>

            {/* Active model badge */}
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 px-4 py-2 bg-slate-900 rounded-full border border-slate-700">
                <Cpu size={16} className="text-blue-400" />
                <div className="text-right">
                  <div className="text-slate-300 text-sm font-medium leading-none">
                    {stats?.current_model || 'Loading...'}
                  </div>
                  {stats?.current_provider && (
                    <div className="text-slate-500 text-xs mt-0.5">{stats.current_provider}</div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </header>

        {/* ── Today's Stats ── */}
        <div className="mb-2">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp size={15} className="text-slate-500" />
            <span className="text-sm font-medium text-slate-400">Today's Activity</span>
            <span className="text-xs text-slate-600 ml-1">— resets at midnight</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <StatsCard
              icon={<MessageSquare size={22} className="text-blue-400" />}
              accentClass="bg-blue-500/10"
              value={stats?.messages_today || 0}
              label="Messages Today"
              subtitle="LLM requests and responses sent since midnight"
              secondary={stats?.total_messages}
              secondaryLabel="All time"
              loading={statsLoading}
            />
            <StatsCard
              icon={<Hash size={22} className="text-violet-400" />}
              accentClass="bg-violet-500/10"
              value={stats?.tokens_today || 0}
              label="Tokens Today"
              subtitle="Prompt + completion tokens consumed today (input + output)"
              secondary={totalTokensAllTime}
              secondaryLabel="All time"
              loading={statsLoading}
              formatter={formatTokens}
            />
            <StatsCard
              icon={<Wrench size={22} className="text-amber-400" />}
              accentClass="bg-amber-500/10"
              value={stats?.total_tool_calls || 0}
              label="Tool Executions"
              subtitle="Total tool calls made by the AI since installation (run_command, browser, etc.)"
              loading={statsLoading}
            />
            <StatsCard
              icon={<Radio size={22} className="text-green-400" />}
              accentClass="bg-green-500/10"
              value={stats?.active_conversations || 0}
              label="Active Sessions"
              subtitle="Unique user + channel combinations with messages in the last 24 hours"
              loading={statsLoading}
            />
          </div>
        </div>

        {/* ── Dashboard Grid ── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* Activity Chart — 2/3 width */}
          <div className="lg:col-span-2 bg-slate-900 rounded-xl border border-slate-800 p-6">
            <SectionHeader
              title="14-Day Activity History"
              description="Blue bars = number of LLM API calls per day. Purple line = total tokens consumed (input + output, in thousands)."
            />
            <ActivityChart data={history || []} loading={historyLoading} />
            {!historyLoading && history && history.length > 0 && (
              <div className="mt-3 flex items-start gap-1.5 text-xs text-slate-600">
                <Info size={11} className="mt-0.5 flex-shrink-0" />
                <span>Tokens are logged per LLM call. High token days usually mean complex multi-step tasks with many tool iterations.</span>
              </div>
            )}
          </div>

          {/* Channels — 1/3 width */}
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
            <SectionHeader
              title="Active Channels"
              description="Interfaces where the AI is reachable. Each channel shows the last message and total count."
            />
            <ChannelList />
          </div>

          {/* Live Events — full width */}
          <div className="lg:col-span-3 bg-slate-900 rounded-xl border border-slate-800 p-6">
            <SectionHeader
              title="Live Event Stream"
              description="Real-time feed of system events: messages received, LLM calls, tool executions, and results. Newest events appear at the top."
            />
            <EventLog />
          </div>

          {/* File Browser — full width */}
          <div className="lg:col-span-3 bg-slate-900 rounded-xl border border-slate-800 p-6">
            <SectionHeader
              title={`Generated Files  (${mediaFiles?.length ?? 0})`}
              description="Files created by the AI during tool use — screenshots, Python plots, PDFs, 3D models, and other exports. All files are stored locally in the workspace folder."
            />
            {!mediaFiles || mediaFiles.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-center gap-2">
                <File size={32} className="text-slate-700" />
                <p className="text-slate-500 text-sm">No files yet</p>
                <p className="text-slate-600 text-xs max-w-sm">
                  When the AI uses tools like <span className="font-mono text-slate-500">screenshot</span>, <span className="font-mono text-slate-500">run_python</span> (with matplotlib), or generates documents, the files will appear here for download.
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-500 border-b border-slate-800">
                      <th className="pb-2 pr-4 font-medium">File</th>
                      <th className="pb-2 pr-4 font-medium">Size</th>
                      <th className="pb-2 pr-4 font-medium">Modified</th>
                      <th className="pb-2 font-medium" />
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
