'use client';

import { ReactNode } from 'react';

interface StatsCardProps {
  icon: ReactNode;
  value: number | string;
  label: string;
  loading?: boolean;
  formatter?: (value: number) => string;
}

export function StatsCard({ icon, value, label, loading, formatter }: StatsCardProps) {
  const displayValue = typeof value === 'number' && formatter ? formatter(value) : value;
  
  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 flex items-center gap-4 hover:border-slate-700 transition-colors">
      <div className="p-3 bg-slate-800 rounded-lg">
        {icon}
      </div>
      <div>
        {loading ? (
          <div className="h-8 w-16 bg-slate-800 rounded animate-pulse"></div>
        ) : (
          <div className="text-2xl font-bold text-white">{displayValue}</div>
        )}
        <div className="text-sm text-slate-400">{label}</div>
      </div>
    </div>
  );
}
