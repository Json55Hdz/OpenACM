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

// Approximate hex equivalents of design tokens (oklch → canvas-safe rgb)
// --acm-accent:  oklch(0.84 0.16 82)  ≈ amber #d4a736
// --acm-ok:      oklch(0.75 0.09 160) ≈ green #52b788
const ACCENT   = '#d4a736'; // amber — matches --acm-accent
const ACCENT_T = 'rgba(212, 167, 54, 0.55)';
const OK       = '#52b788'; // green — matches --acm-ok
const OK_T     = 'rgba(82, 183, 136, 0.08)';

const GRID      = 'rgba(255,255,255,0.04)';
const TICK      = '#52556a';
const TOOLTIP_BG = 'rgba(20, 22, 36, 0.96)';
const TOOLTIP_BD = 'rgba(60, 63, 90, 0.8)';

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
        <div
          className="animate-spin rounded-full h-8 w-8 border-b-2"
          style={{ borderColor: 'var(--acm-accent)' }}
        />
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="h-64 flex flex-col items-center justify-center gap-2 text-center">
        <div className="text-sm" style={{ color: 'var(--acm-fg-3)' }}>
          No activity data yet
        </div>
        <div className="text-xs max-w-xs" style={{ color: 'var(--acm-fg-4)' }}>
          Charts will populate after the first LLM requests are made. Each bar represents one day of token usage.
        </div>
      </div>
    );
  }

  const labels = data.map(d => {
    const date = new Date(d.date + 'T00:00:00');
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  });

  const tokensK = data.map(d => Math.round((d.tokens || 0) / 100) / 10);
  const requests = data.map(d => d.requests || 0);

  const chartData = {
    labels,
    datasets: [
      {
        label: 'Tokens (K)',
        data: tokensK,
        backgroundColor: ACCENT_T,
        borderColor: ACCENT,
        borderWidth: 1,
        borderRadius: 5,
        borderSkipped: false,
        yAxisID: 'yTokens',
        type: 'bar' as const,
      },
      {
        label: 'LLM Requests',
        data: requests,
        borderColor: OK,
        backgroundColor: OK_T,
        borderWidth: 2,
        pointRadius: 3,
        pointHoverRadius: 5,
        pointBackgroundColor: OK,
        fill: true,
        tension: 0.4,
        yAxisID: 'yRequests',
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
          color: TICK,
          font: { family: 'Inter', size: 11 },
          boxWidth: 12,
          padding: 16,
        },
      },
      tooltip: {
        backgroundColor: TOOLTIP_BG,
        borderColor: TOOLTIP_BD,
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
        grid: { color: GRID },
        ticks: { color: TICK, font: { size: 10 } },
        border: { color: 'rgba(255,255,255,0.05)' },
      },
      yTokens: {
        position: 'left' as const,
        grid: { color: GRID },
        ticks: {
          color: ACCENT,
          font: { size: 10 },
          callback: (v: number | string) => `${v}K`,
        },
        title: {
          display: true,
          text: 'Tokens (K)',
          color: ACCENT,
          font: { size: 10 },
        },
        border: { color: 'rgba(255,255,255,0.05)' },
      },
      yRequests: {
        position: 'right' as const,
        grid: { display: false },
        ticks: {
          color: OK,
          font: { size: 10 },
          stepSize: 1,
        },
        title: {
          display: true,
          text: 'Requests',
          color: OK,
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
