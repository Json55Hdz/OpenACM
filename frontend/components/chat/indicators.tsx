'use client';

import { Send, MessageSquare, SquareTerminal, Sparkles, BrainCircuit, Gamepad2 } from 'lucide-react';
import { cn } from './shared';


export function ChannelIcon({ channelType, className }: { channelType?: string; className?: string }) {
  switch (channelType?.toLowerCase()) {
    case 'whatsapp':
      return (
        <span
          className={cn("flex items-center justify-center w-5 h-5 rounded-[4px] bg-[#25D366]/15 text-[#25D366] shrink-0", className)}
          title="WhatsApp"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
          </svg>
        </span>
      );
    case 'telegram':
      return (
        <span
          className={cn("flex items-center justify-center w-5 h-5 rounded-[4px] bg-[#0088cc]/15 text-[#0088cc] shrink-0", className)}
          title="Telegram"
        >
          <Send className="w-3 h-3 -translate-x-0.5" />
        </span>
      );
    case 'discord':
      return (
        <span
          className={cn("flex items-center justify-center w-5 h-5 rounded-[4px] bg-[#5865F2]/15 text-[#5865F2] shrink-0", className)}
          title="Discord"
        >
          <Gamepad2 className="w-3 h-3" />
        </span>
      );
    case 'console':
      return (
        <span
          className={cn("flex items-center justify-center w-5 h-5 rounded-[4px] bg-amber-500/15 text-amber-400 shrink-0", className)}
          title="Console"
        >
          <SquareTerminal className="w-3 h-3" />
        </span>
      );
    case 'web':
    default:
      return (
        <span
          className={cn("flex items-center justify-center w-5 h-5 rounded-[4px] bg-[var(--acm-accent)]/15 text-[var(--acm-accent)] shrink-0", className)}
          title="Web"
        >
          <MessageSquare className="w-3 h-3" />
        </span>
      );
  }
}

export function RouterLearningIndicator() {
  return (
    <div className="flex items-center gap-[7px] px-[10px] py-[4px] bg-[oklch(0.84_0.16_82/0.1)] border border-[var(--acm-accent)] rounded-full text-[var(--acm-accent)] text-[11px]">
      <Sparkles size={11} className="acm-pulse" />
      <span className="mono">Learning...</span>
    </div>
  );
}

export function MemoryRecallIndicator({ status, count }: {
  status: 'searching' | 'found' | 'empty' | 'saving' | 'saved';
  count: number;
}) {
  const isBusy  = status === 'searching' || status === 'saving';
  const isGood  = status === 'found' || status === 'saved';
  const isEmpty = status === 'empty';

  const label =
    status === 'searching' ? 'Searching memory...' :
    status === 'found'     ? `Memory: ${count} ${count === 1 ? 'fragment' : 'fragments'}` :
    status === 'saving'    ? 'Saving to memory...' :
    status === 'saved'     ? 'Saved to memory' :
                             'No memory results';

  return (
    <div className={cn(
      'inline-flex items-center gap-[7px] px-[10px] py-[4px] border rounded-full text-[11px] transition-all duration-300',
      isBusy  && 'border-[var(--acm-border-strong)] text-[var(--acm-fg-3)]',
      isGood  && 'border-[var(--acm-accent)] text-[var(--acm-accent)] bg-[oklch(0.84_0.16_82/0.07)]',
      isEmpty && 'border-[var(--acm-border)] text-[var(--acm-fg-4)]',
    )}>
      <BrainCircuit size={11} className={cn(
        isBusy  && 'acm-pulse text-[var(--acm-fg-3)]',
        isGood  && 'text-[var(--acm-accent)]',
        isEmpty && 'text-[var(--acm-fg-4)]',
      )} />
      <span className="mono">{label}</span>
    </div>
  );
}

export function SkillActiveIndicator({ names }: { names: string[] }) {
  const label = names
    .map((n) => n.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()))
    .join(', ');
  return (
    <div className="inline-flex items-center gap-[7px] px-[10px] py-[4px] border border-[var(--acm-accent)] bg-[oklch(0.84_0.16_82/0.07)] rounded-full text-[var(--acm-accent)] text-[11px]">
      <span className="dot dot-accent acm-pulse" />
      <span className="mono">Skill: {label}</span>
    </div>
  );
}

export function ContextBadge({ pct, tokens, window: win }: { pct: number | null; tokens: number; window: number }) {
  if (pct === null) {
    return (
      <span className="inline-flex items-center px-[8px] py-[3px] rounded-full border border-[var(--acm-border)] mono text-[10px] text-[var(--acm-fg-4)]">
        — ctx
      </span>
    );
  }
  const color =
    pct >= 90 ? 'text-[var(--acm-err)] border-[var(--acm-err)]' :
    pct >= 75 ? 'text-[var(--acm-warn)] border-[var(--acm-warn)]' :
    pct >= 50 ? 'text-[oklch(0.75_0.12_55)] border-[oklch(0.75_0.12_55)]' :
    'text-[var(--acm-fg-4)] border-[var(--acm-border)]';
  const tip = `~${tokens.toLocaleString()} / ${win.toLocaleString()} tokens (${pct}%)`;
  return (
    <span
      title={tip}
      className={`inline-flex items-center gap-[4px] px-[8px] py-[3px] rounded-full border mono text-[10px] transition-colors ${color}`}
    >
      {pct >= 90 ? '⚠ ' : ''}{pct}% ctx
    </span>
  );
}

export function TypingIndicator({ label }: { label?: string | null }) {
  return (
    <div className="flex items-center gap-3 pl-1 py-1">
      <div className="flex items-center gap-[5px]">
        <div className="w-[7px] h-[7px] rounded-full bg-[var(--acm-accent)] acm-pulse" style={{ animationDelay: '0ms' }} />
        <div className="w-[7px] h-[7px] rounded-full bg-[var(--acm-accent)] acm-pulse" style={{ animationDelay: '220ms' }} />
        <div className="w-[7px] h-[7px] rounded-full bg-[var(--acm-accent)] acm-pulse" style={{ animationDelay: '440ms' }} />
      </div>
      {label && <span className="mono text-[11px] text-[var(--acm-fg-3)] truncate">{label}</span>}
    </div>
  );
}
