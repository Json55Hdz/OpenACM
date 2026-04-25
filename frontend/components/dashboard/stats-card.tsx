'use client';

import { ReactNode, useState } from 'react';

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
  accentClass = 'bg-amber-500/10',
}: StatsCardProps) {
  const [hovered, setHovered] = useState(false);
  const displayValue = typeof value === 'number' && formatter ? formatter(value) : value;

  return (
    <div
      className="flex flex-col gap-3 p-5"
      style={{
        background: 'var(--acm-card)',
        border: `1px solid ${hovered ? 'oklch(0.84 0.16 82 / 0.3)' : 'var(--acm-border)'}`,
        borderRadius: 'var(--acm-radius)',
        transition: 'border-color 160ms ease',
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="flex items-start justify-between">
        <div className={`p-2.5 rounded-lg ${accentClass}`}>
          {icon}
        </div>
        {secondary !== undefined && !loading && (
          <div className="text-right">
            <div className="text-xs" style={{ color: 'var(--acm-fg-4)' }}>
              {secondaryLabel || 'All time'}
            </div>
            <div className="text-sm font-semibold" style={{ color: 'var(--acm-fg-3)' }}>
              {typeof secondary === 'number' && formatter ? formatter(secondary) : secondary}
            </div>
          </div>
        )}
      </div>
      <div>
        {loading ? (
          <>
            <div
              className="h-7 w-20 rounded animate-pulse mb-1"
              style={{ background: 'var(--acm-elev)' }}
            />
            <div
              className="h-3.5 w-28 rounded animate-pulse"
              style={{ background: 'var(--acm-elev)', opacity: 0.6 }}
            />
          </>
        ) : (
          <>
            <div className="text-2xl font-bold" style={{ color: 'var(--acm-fg)' }}>
              {displayValue}
            </div>
            <div className="text-sm font-medium mt-0.5" style={{ color: 'var(--acm-fg-3)' }}>
              {label}
            </div>
            {subtitle && (
              <div className="text-xs mt-1 leading-snug" style={{ color: 'var(--acm-fg-4)' }}>
                {subtitle}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
