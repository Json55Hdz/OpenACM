export function ACMMark({ size = 24, color = 'currentColor' }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M7 9 L15 16 L7 23" stroke={color} strokeWidth="2.2" strokeLinecap="square" strokeLinejoin="miter" />
      <path d="M15 16 L21 16" stroke={color} strokeWidth="2.2" strokeLinecap="square" />
      <circle cx="24.5" cy="16" r="2.2" fill={color} />
      <path d="M26.5 17.8 L29 20.2" stroke={color} strokeWidth="1.6" strokeLinecap="square" />
    </svg>
  );
}

export function SignalStripe({
  active = 2,
  total = 4,
  color,
}: {
  active?: number;
  total?: number;
  color?: string;
}) {
  return (
    <span className="inline-flex items-end gap-0.5">
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          style={{
            display: 'inline-block',
            width: 2,
            height: 6 + i * 2,
            borderRadius: 1,
            background: i < active
              ? (color || 'var(--acm-accent)')
              : 'var(--acm-border-strong)',
          }}
        />
      ))}
    </span>
  );
}
