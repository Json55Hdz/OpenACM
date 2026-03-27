'use client';

import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import { Chart } from 'react-chartjs-2';

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Title,
  Tooltip,
  Legend
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
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
      </div>
    );
  }
  
  if (!data || data.length === 0) {
    return (
      <div className="h-64 flex items-center justify-center text-slate-500">
        No hay datos de actividad disponibles
      </div>
    );
  }
  
  const labels = data.map(d => {
    const date = new Date(d.date);
    return date.toLocaleDateString('es-ES', { day: '2-digit', month: 'short' });
  });
  
  const requests = data.map(d => d.requests || 0);
  const tokens = data.map(d => (d.tokens || 0) / 1000);
  
  const chartData = {
    labels,
    datasets: [
      {
        label: 'Requests',
        data: requests,
        backgroundColor: 'rgba(59, 130, 246, 0.6)',
        borderColor: 'rgba(59, 130, 246, 1)',
        borderWidth: 1,
        borderRadius: 4,
        yAxisID: 'y',
        type: 'bar' as const,
      },
      {
        label: 'Tokens (K)',
        data: tokens,
        borderColor: 'rgba(139, 92, 246, 1)',
        backgroundColor: 'rgba(139, 92, 246, 0.1)',
        borderWidth: 2,
        pointRadius: 3,
        pointBackgroundColor: 'rgba(139, 92, 246, 1)',
        fill: true,
        tension: 0.4,
        yAxisID: 'y1',
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
        labels: {
          color: '#94a3b8',
          font: { family: 'Inter', size: 11 },
        },
      },
    },
    scales: {
      x: {
        grid: { color: 'rgba(255,255,255,0.04)' },
        ticks: { color: '#64748b', font: { size: 10 } },
      },
      y: {
        position: 'left' as const,
        grid: { color: 'rgba(255,255,255,0.04)' },
        ticks: { color: '#64748b', font: { size: 10 } },
      },
      y1: {
        position: 'right' as const,
        grid: { display: false },
        ticks: { color: '#8b5cf6', font: { size: 10 } },
      },
    },
  };
  
  return (
    <div className="h-64">
      <Chart type="bar" data={chartData} options={options} />
    </div>
  );
}
