'use client';

import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  BarController,
  LineElement,
  LineController,
  PointElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import { Chart } from 'react-chartjs-2';

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  BarController,
  LineElement,
  LineController,
  PointElement,
  Title,
  Tooltip,
  Legend,
  Filler,
);

interface ActivityData {
  date: string;
  requests: number;
  tokens: number;
}

interface ActivityChartProps {
  data: ActivityData[];
  loading?: boolean;
}

export function ActivityChart({ data, loading }: ActivityChartProps) {
  if (loading) {
    return (
      <div className="h-64 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="h-64 flex flex-col items-center justify-center gap-2 text-center">
        <div className="text-slate-500 text-sm">No activity data yet</div>
        <div className="text-slate-600 text-xs max-w-xs">
          Charts will populate after the first LLM requests are made. Each bar represents one day of usage.
        </div>
      </div>
    );
  }

  const labels = data.map(d => {
    const date = new Date(d.date + 'T00:00:00');
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  });

  const requests = data.map(d => d.requests || 0);
  const tokensK = data.map(d => Math.round((d.tokens || 0) / 100) / 10); // 1 decimal K

  const chartData = {
    labels,
    datasets: [
      {
        label: 'LLM Requests',
        data: requests,
        backgroundColor: 'rgba(59, 130, 246, 0.55)',
        borderColor: 'rgba(59, 130, 246, 0.9)',
        borderWidth: 1,
        borderRadius: 5,
        borderSkipped: false,
        yAxisID: 'yRequests',
        type: 'bar' as const,
      },
      {
        label: 'Tokens (K)',
        data: tokensK,
        borderColor: 'rgba(139, 92, 246, 0.9)',
        backgroundColor: 'rgba(139, 92, 246, 0.08)',
        borderWidth: 2,
        pointRadius: 3,
        pointHoverRadius: 5,
        pointBackgroundColor: 'rgba(139, 92, 246, 1)',
        fill: true,
        tension: 0.4,
        yAxisID: 'yTokens',
        type: 'line' as const,
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      mode: 'index' as const,
      intersect: false,
    },
    plugins: {
      legend: {
        display: true,
        position: 'top' as const,
        align: 'end' as const,
        labels: {
          color: '#94a3b8',
          font: { family: 'Inter', size: 11 },
          boxWidth: 12,
          padding: 16,
        },
      },
      tooltip: {
        backgroundColor: 'rgba(15, 23, 42, 0.95)',
        borderColor: 'rgba(51, 65, 85, 0.8)',
        borderWidth: 1,
        titleColor: '#e2e8f0',
        bodyColor: '#94a3b8',
        padding: 10,
        callbacks: {
          label: (ctx: { dataset: { label?: string }; raw: unknown }) => {
            const label = ctx.dataset.label || '';
            const raw = ctx.raw as number;
            if (label.includes('Token')) return ` Tokens: ${(raw * 1000).toLocaleString()}`;
            return ` Requests: ${raw}`;
          },
        },
      },
    },
    scales: {
      x: {
        grid: { color: 'rgba(255,255,255,0.03)' },
        ticks: { color: '#64748b', font: { size: 10 } },
        border: { color: 'rgba(255,255,255,0.05)' },
      },
      yRequests: {
        position: 'left' as const,
        grid: { color: 'rgba(255,255,255,0.04)' },
        ticks: {
          color: '#64748b',
          font: { size: 10 },
          stepSize: 1,
        },
        title: {
          display: true,
          text: 'Requests',
          color: '#64748b',
          font: { size: 10 },
        },
        border: { color: 'rgba(255,255,255,0.05)' },
      },
      yTokens: {
        position: 'right' as const,
        grid: { display: false },
        ticks: {
          color: '#8b5cf6',
          font: { size: 10 },
          callback: (v: number | string) => `${v}K`,
        },
        title: {
          display: true,
          text: 'Tokens (K)',
          color: '#8b5cf6',
          font: { size: 10 },
        },
        border: { color: 'transparent' },
      },
    },
  };

  return (
    <div className="h-64">
      <Chart type="bar" data={chartData} options={options as Parameters<typeof Chart>[0]['options']} />
    </div>
  );
}
