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

export function AutoReplyChart({ data }: { data: StatsData['autoreply'] }) {
  const chartData = {
    labels: ['Sugerencias IA', 'Borradores', 'Ejemplos aprendidos'],
    datasets: [{
      label: 'Cantidad',
      data: [data.suggestions_generated, data.drafts_saved, data.examples_learned],
      backgroundColor: [
        'rgba(99,102,241,0.7)',
        'rgba(34,197,94,0.7)',
        'rgba(251,191,36,0.7)',
      ],
    }],
  };
  const options = {
    responsive: true,
    plugins: {
      legend: { display: false },
      title: { display: true, text: 'Sistema Auto-reply' },
    },
    scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
  };
  return (
    <div className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4">
      <Bar data={chartData} options={options} />
    </div>
  );
}
