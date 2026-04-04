'use client';

import { ReactNode } from 'react';

interface StatsCardProps {
  icon: ReactNode;
  value: number | string;
  label: string;
  subtitle?: string;
  secondary?: string | number;
  secondaryLabel?: string;
  loading?: boolean;
  formatter?: (value: number) => string;
  accentClass?: string;
}

export function StatsCard({
  icon,
  value,
  label,
  subtitle,
  secondary,
  secondaryLabel,
  loading,
  formatter,
  accentClass = 'bg-slate-800',
}: StatsCardProps) {
  const displayValue = typeof value === 'number' && formatter ? formatter(value) : value;

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-5 hover:border-slate-700 transition-colors flex flex-col gap-3">
      <div className="flex items-start justify-between">
        <div className={`p-2.5 rounded-lg ${accentClass}`}>
          {icon}
        </div>
        {secondary !== undefined && !loading && (
          <div className="text-right">
            <div className="text-xs text-slate-500">{secondaryLabel || 'All time'}</div>
            <div className="text-sm font-semibold text-slate-400">
              {typeof secondary === 'number' && formatter ? formatter(secondary) : secondary}
            </div>
          </div>
        )}
      </div>
      <div>
        {loading ? (
          <>
            <div className="h-7 w-20 bg-slate-800 rounded animate-pulse mb-1" />
            <div className="h-3.5 w-28 bg-slate-800/60 rounded animate-pulse" />
          </>
        ) : (
          <>
            <div className="text-2xl font-bold text-white">{displayValue}</div>
            <div className="text-sm font-medium text-slate-400 mt-0.5">{label}</div>
            {subtitle && <div className="text-xs text-slate-600 mt-1 leading-snug">{subtitle}</div>}
          </>
        )}
      </div>
    </div>
  );
}
