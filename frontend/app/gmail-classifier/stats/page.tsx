'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { ArrowLeft, Download, Printer } from 'lucide-react';
import { useAuthStore } from '@/stores/auth-store';
import { AppLayout } from '@/components/layout/app-layout';
import { KpiCards } from './components/KpiCards';
import { VolumeChart } from './components/VolumeChart';
import { CategoryChart } from './components/CategoryChart';
import { TopSendersChart } from './components/TopSendersChart';
import { AutoReplyChart } from './components/AutoReplyChart';
import { ReadStatusChart } from './components/ReadStatusChart';

const API = '/api/gmail-classifier';

function toDateStr(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export type StatsData = {
  period: { from: string; to: string; total_emails: number };
  volume_by_day: { date: string; count: number }[];
  by_category: {
    id: number; name: string; color: string;
    total: number; read: number; replied: number; ai_classified: number;
  }[];
  top_senders: { email: string; name: string; count: number }[];
  reply_rate: { total: number; replied: number; rate: number };
  read_status: { total: number; read: number; unread: number; rate: number };
  autoreply: {
    suggestions_generated: number;
    drafts_saved: number;
    examples_learned: number;
    avg_use_count: number;
  };
};

export default function StatsPage() {
  const token = useAuthStore(s => s.token);

  const today = new Date();
  const [fromDate, setFromDate] = useState(
    toDateStr(new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000))
  );
  const [toDate, setToDate] = useState(toDateStr(today));
  const [stats, setStats] = useState<StatsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = useCallback(async () => {
    if (fromDate > toDate) {
      setError('La fecha de inicio debe ser anterior o igual a la de fin');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/stats?from_date=${fromDate}&to_date=${toDate}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Error del servidor');
      setStats(await res.json());
    } catch {
      setError('No se pudieron cargar las estadísticas. Intenta de nuevo.');
    } finally {
      setLoading(false);
    }
  }, [fromDate, toDate, token]);

  useEffect(() => { fetchStats(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleExcelDownload = async () => {
    try {
      const res = await fetch(
        `${API}/export/excel?from_date=${fromDate}&to_date=${toDate}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `gmail_stats_${fromDate}_${toDate}.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      alert('Error al generar el Excel. Intenta de nuevo.');
    }
  };

  return (
    <AppLayout>
      <div className="p-6 max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6 no-print">
          <div className="flex items-center gap-3">
            <Link href="/gmail-classifier" className="text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)]">
              <ArrowLeft size={18} />
            </Link>
            <h1 className="text-lg font-semibold">Estadísticas Gmail</h1>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={fromDate}
              onChange={e => setFromDate(e.target.value)}
              className="text-sm border border-[var(--acm-border)] rounded px-2 py-1 bg-[var(--acm-bg)] text-[var(--acm-fg)]"
            />
            <span className="text-[var(--acm-fg-3)] text-sm">→</span>
            <input
              type="date"
              value={toDate}
              onChange={e => setToDate(e.target.value)}
              className="text-sm border border-[var(--acm-border)] rounded px-2 py-1 bg-[var(--acm-bg)] text-[var(--acm-fg)]"
            />
            <button onClick={fetchStats} className="btn-secondary text-[12px] py-[7px] px-3">
              Aplicar
            </button>
            <button
              onClick={() => window.print()}
              className="btn-secondary text-[12px] py-[7px] px-3 flex items-center gap-1"
            >
              <Printer size={13} /> PDF
            </button>
            <button
              onClick={handleExcelDownload}
              className="btn-secondary text-[12px] py-[7px] px-3 flex items-center gap-1"
            >
              <Download size={13} /> Excel
            </button>
          </div>
        </div>

        {/* States */}
        {error && (
          <div className="text-sm text-red-500 mb-4">{error}</div>
        )}
        {loading && (
          <div className="flex items-center justify-center py-20 text-[var(--acm-fg-3)]">
            <div className="h-5 w-5 rounded-full border-2 border-current border-t-transparent animate-spin mr-3" />
            Cargando estadísticas...
          </div>
        )}
        {!loading && stats && (
          <div className="charts-container space-y-6">
            <KpiCards stats={stats} />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <VolumeChart data={stats.volume_by_day} />
              <CategoryChart data={stats.by_category} />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <TopSendersChart data={stats.top_senders} />
              <AutoReplyChart data={stats.autoreply} />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <ReadStatusChart data={stats.read_status} />
            </div>
          </div>
        )}
      </div>

      <style>{`
        @media print {
          .no-print { display: none !important; }
          .charts-container { page-break-inside: avoid; }
          body { background: white !important; }
        }
      `}</style>
    </AppLayout>
  );
}
