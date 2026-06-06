'use client';
import { Bar } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import type { StatsData } from '../page';

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

export function TopSendersChart({ data }: { data: StatsData['top_senders'] }) {
  if (data.length === 0) {
    return (
      <div className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4 flex items-center justify-center h-40 text-[var(--acm-fg-3)] text-sm">
        Top remitentes — sin datos
      </div>
    );
  }
  const chartData = {
    labels: data.map(s => s.name || s.email),
    datasets: [{
      label: 'Emails enviados',
      data: data.map(s => s.count),
      backgroundColor: 'rgba(168,85,247,0.7)',
    }],
  };
  const options = {
    indexAxis: 'y' as const,
    responsive: true,
    plugins: {
      legend: { display: false },
      title: { display: true, text: 'Top 10 remitentes' },
    },
    scales: { x: { beginAtZero: true, ticks: { stepSize: 1 } } },
  };
  return (
    <div className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4">
      <Bar data={chartData} options={options} />
    </div>
  );
}
