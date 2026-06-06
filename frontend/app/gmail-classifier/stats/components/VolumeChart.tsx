'use client';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import type { StatsData } from '../page';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

export function VolumeChart({ data }: { data: StatsData['volume_by_day'] }) {
  if (data.length === 0) {
    return (
      <div className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4 flex items-center justify-center h-40 text-[var(--acm-fg-3)] text-sm">
        Volumen diario — sin datos
      </div>
    );
  }
  const chartData = {
    labels: data.map(d => d.date),
    datasets: [{
      label: 'Emails recibidos',
      data: data.map(d => d.count),
      borderColor: 'rgb(99, 102, 241)',
      backgroundColor: 'rgba(99, 102, 241, 0.1)',
      fill: true,
      tension: 0.3,
    }],
  };
  const options = {
    responsive: true,
    plugins: {
      legend: { display: false },
      title: { display: true, text: 'Volumen diario' },
    },
    scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
  };
  return (
    <div className="bg-[var(--acm-elev)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] p-4">
      <Line data={chartData} options={options} />
    </div>
  );
}
