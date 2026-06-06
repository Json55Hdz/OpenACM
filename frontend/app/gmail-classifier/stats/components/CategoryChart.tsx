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

export function CategoryChart({ data }: { data: StatsData['by_category'] }) {
  const filtered = data.filter(c => c.total > 0);
  if (filtered.length === 0) {
    return (
      <div className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4 flex items-center justify-center h-40 text-[var(--acm-fg-3)] text-sm">
        Por categoría — sin datos
      </div>
    );
  }
  const chartData = {
    labels: filtered.map(c => c.name),
    datasets: [
      { label: 'Total',        data: filtered.map(c => c.total),   backgroundColor: 'rgba(99,102,241,0.7)' },
      { label: 'Leídos',       data: filtered.map(c => c.read),    backgroundColor: 'rgba(34,197,94,0.7)' },
      { label: 'Respondidos',  data: filtered.map(c => c.replied), backgroundColor: 'rgba(251,191,36,0.7)' },
    ],
  };
  const options = {
    responsive: true,
    plugins: { title: { display: true, text: 'Por categoría' } },
    scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
  };
  return (
    <div className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4">
      <Bar data={chartData} options={options} />
    </div>
  );
}
