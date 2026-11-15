'use client';

import { Copy, ToggleLeft, ToggleRight } from 'lucide-react';
import { toast } from 'sonner';


export function ConfigSection({
  title,
  subtitle,
  icon: Icon,
  children,
  id,
}: {
  title: string;
  subtitle?: string;
  icon: React.ElementType;
  children: React.ReactNode;
  id?: string;
}) {
  return (
    <div
      id={id}
      style={{
        background: 'var(--acm-card)',
        border: '1px solid var(--acm-border)',
        borderRadius: 'var(--acm-radius)',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          borderBottom: '1px solid var(--acm-border)',
          padding: '14px 20px',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            background: 'var(--acm-elev)',
            borderRadius: 6,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            color: 'var(--acm-accent)',
          }}
        >
          <Icon size={16} />
        </div>
        <div>
          <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--acm-fg)' }}>{title}</div>
          {subtitle && (
            <div className="mono" style={{ fontSize: 11, color: 'var(--acm-fg-4)', marginTop: 2 }}>
              {subtitle}
            </div>
          )}
        </div>
      </div>
      <div style={{ padding: '20px' }}>{children}</div>
    </div>
  );
}

// ─── Divider ──────────────────────────────────────────────────────────────────

export function Divider() {
  return (
    <div style={{ height: 1, background: 'var(--acm-border)', margin: '16px 0' }} />
  );
}

// ─── Toggle row ───────────────────────────────────────────────────────────────

export function ToggleRow({
  label,
  description,
  value,
  onToggle,
  disabled = false,
  badge,
}: {
  label: string;
  description?: string;
  value: boolean;
  onToggle: () => void;
  disabled?: boolean;
  badge?: React.ReactNode;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--acm-fg-2)', fontSize: 13, fontWeight: 500 }}>
          {label}
          {badge}
        </div>
        {description && (
          <p style={{ fontSize: 11, color: 'var(--acm-fg-4)', marginTop: 3 }}>{description}</p>
        )}
      </div>
      <button
        onClick={onToggle}
        disabled={disabled}
        style={{
          color: value ? 'var(--acm-accent)' : 'var(--acm-fg-4)',
          background: 'none',
          border: 'none',
          cursor: disabled ? 'not-allowed' : 'pointer',
          padding: 0,
          opacity: disabled ? 0.4 : 1,
          flexShrink: 0,
        }}
      >
        {value ? <ToggleRight size={26} /> : <ToggleLeft size={26} />}
      </button>
    </div>
  );
}

// ─── Stat tile ────────────────────────────────────────────────────────────────

export function StatTile({
  label,
  value,
  sub,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon?: React.ElementType;
}) {
  return (
    <div
      style={{
        border: '1px solid var(--acm-border)',
        borderRadius: 'var(--acm-radius)',
        padding: '14px 16px',
        background: 'var(--acm-elev)',
      }}
    >
      <div className="label" style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
        {Icon && <Icon size={11} style={{ color: 'var(--acm-accent)' }} />}
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--acm-fg)', lineHeight: 1 }}>{value}</div>
      {sub && <div className="mono" style={{ fontSize: 10, color: 'var(--acm-fg-4)', marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

// ─── Info row ─────────────────────────────────────────────────────────────────

export function InfoRow({ label, value, copyable = false }: { label: string; value: string; copyable?: boolean }) {
  const handleCopy = () => {
    navigator.clipboard.writeText(value);
    toast.success('Copied to clipboard');
  };
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '10px 0',
        borderBottom: '1px solid var(--acm-border)',
      }}
    >
      <span style={{ fontSize: 12, color: 'var(--acm-fg-3)' }}>{label}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span className="mono" style={{ fontSize: 12, color: 'var(--acm-fg-2)' }}>{value}</span>
        {copyable && (
          <button
            onClick={handleCopy}
            style={{ color: 'var(--acm-fg-4)', background: 'none', border: 'none', cursor: 'pointer', padding: 2 }}
          >
            <Copy size={12} />
          </button>
        )}
      </div>
    </div>
  );
}

// ─── RAG threshold control ────────────────────────────────────────────────────

export function NavItem({
  label,
  icon: Icon,
  active,
  onClick,
}: {
  label: string;
  icon: React.ElementType;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        width: '100%',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 12px',
        fontSize: 13,
        fontWeight: active ? 600 : 400,
        color: active ? 'var(--acm-accent)' : 'var(--acm-fg-3)',
        background: active ? 'var(--acm-card)' : 'transparent',
        borderRadius: 6,
        border: 'none',
        borderLeft: active ? '2px solid var(--acm-accent)' : '2px solid transparent',
        cursor: 'pointer',
        textAlign: 'left',
        transition: 'all 140ms ease',
      }}
      className={active ? '' : 'nav-inactive'}
    >
      <Icon size={14} style={{ flexShrink: 0 }} />
      {label}
    </button>
  );
}

// ─── Nav group label ──────────────────────────────────────────────────────────

export function NavGroupLabel({ children }: { children: string }) {
  return (
    <div className="label" style={{ padding: '12px 12px 4px', color: 'var(--acm-fg-4)' }}>
      {children}
    </div>
  );
}

// ─── Provider card ────────────────────────────────────────────────────────────
