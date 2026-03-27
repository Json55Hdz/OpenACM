'use client';

import { useEffect } from 'react';
import { AppLayout } from '@/components/layout/app-layout';
import { useStats, useActivityHistory } from '@/hooks/use-api';
import { useDashboardStore } from '@/stores/dashboard-store';
import { ActivityChart } from '@/components/dashboard/activity-chart';
import { StatsCard } from '@/components/dashboard/stats-card';
import { ChannelList } from '@/components/dashboard/channel-list';
import { EventLog } from '@/components/dashboard/event-log';
import { MessageSquare, Hash, Wrench, Radio } from 'lucide-react';

export default function DashboardPage() {
  const { data: stats, isLoading: statsLoading } = useStats();
  const { data: history, isLoading: historyLoading } = useActivityHistory();
  const { setStats, setOnline } = useDashboardStore();
  
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
        </div>
      </div>
    </AppLayout>
  );
}
