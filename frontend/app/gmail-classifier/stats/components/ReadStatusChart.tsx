'use client';
import { Doughnut } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  ArcElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import type { StatsData } from '../page';

ChartJS.register(ArcElement, Title, Tooltip, Legend);

export function ReadStatusChart({ data }: { data: StatsData['read_status'] }) {
  const chartData = {
    labels: ['Leídos', 'No leídos'],
    datasets: [{
      data: [data.read, data.unread],
      backgroundColor: ['rgba(34,197,94,0.75)', 'rgba(251,146,60,0.75)'],
      borderColor: ['rgba(34,197,94,1)', 'rgba(251,146,60,1)'],
      borderWidth: 1,
    }],
  };
  const options = {
    responsive: true,
    plugins: {
      legend: { position: 'bottom' as const },
      title: { display: true, text: `Estado de lectura · ${(data.rate * 100).toFixed(0)}% leído` },
    },
  };
  return (
    <div className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4 flex items-center justify-center">
      {data.total > 0 ? (
        <Doughnut data={chartData} options={options} />
      ) : (
        <p className="text-sm text-[var(--acm-fg-3)] py-12">Sin datos en el período</p>
      )}
    </div>
  );
}
