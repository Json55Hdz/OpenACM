'use client';

import { Settings, Bot, Shield, Terminal, Send, Globe2, Zap, Paintbrush, Plus, Server, Archive, Brain, Mic, Smartphone } from 'lucide-react';


export function ProviderCard({
  name,
  description,
  active,
  configured,
  onClick,
}: {
  name: string;
  description?: string;
  active: boolean;
  configured: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        background: active
          ? 'var(--acm-accent-soft)'
          : configured
          ? 'var(--acm-elev)'
          : 'var(--acm-card)',
        border: `1px solid ${
          active
            ? 'oklch(0.84 0.16 82 / 0.25)'
            : 'var(--acm-border)'
        }`,
        borderRadius: 'var(--acm-radius)',
        padding: '12px 14px',
        textAlign: 'left',
        cursor: 'pointer',
        width: '100%',
        opacity: configured ? 1 : 0.5,
        transition: 'all 140ms ease',
      }}
    >
      <div
        style={{
          fontWeight: 600,
          fontSize: 13,
          color: active ? 'var(--acm-accent)' : 'var(--acm-fg-2)',
          marginBottom: 2,
        }}
      >
        {name}
      </div>
      {description && (
        <div className="mono" style={{ fontSize: 10, color: 'var(--acm-fg-4)', lineHeight: 1.4 }}>
          {description}
        </div>
      )}
      {active && (
        <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 4 }}>
          <span className="dot dot-ok" />
          <span style={{ fontSize: 10, color: 'var(--acm-ok)' }}>Active</span>
        </div>
      )}
    </button>
  );
}

// ─── Custom provider card (dashed) ────────────────────────────────────────────

export function AddProviderCard({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: 'transparent',
        border: '1px dashed var(--acm-border-strong)',
        borderRadius: 'var(--acm-radius)',
        padding: '12px 14px',
        textAlign: 'center',
        cursor: 'pointer',
        width: '100%',
        color: 'var(--acm-fg-4)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 6,
        transition: 'all 140ms ease',
      }}
      className="nav-inactive"
    >
      <Plus size={16} />
      <span style={{ fontSize: 12 }}>Add Custom Provider</span>
    </button>
  );
}

// ─── Main config page ─────────────────────────────────────────────────────────
