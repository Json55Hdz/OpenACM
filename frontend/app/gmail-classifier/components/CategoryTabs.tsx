'use client';

import { Settings2 } from 'lucide-react';

interface Category {
  id: number;
  name: string;
  color: string;
  icon: string;
  email_count: number;
}

interface CategoryTabsProps {
  categories: Category[];
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  onManage: () => void;
}

export function CategoryTabs({ categories, selectedId, onSelect, onManage }: CategoryTabsProps) {
  const totalCount = categories.reduce((sum, c) => sum + c.email_count, 0);

  return (
    <div className="flex items-center gap-0.5 px-4 py-2 overflow-x-auto">
      {/* Todo tab */}
      <button
        onClick={() => onSelect(null)}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--acm-radius)] text-[12px] font-medium whitespace-nowrap transition-colors ${
          selectedId === null
            ? 'acm-active-pill'
            : 'text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)] hover:bg-[var(--acm-elev)]'
        }`}
      >
        Todo
        {totalCount > 0 && (
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full mono ${
            selectedId === null
              ? 'bg-black/20 text-[oklch(0.18_0.015_80)]'
              : 'bg-[var(--acm-elev)] text-[var(--acm-fg-3)]'
          }`}>
            {totalCount}
          </span>
        )}
      </button>

      {/* Category tabs */}
      {categories.map(cat => {
        const isActive = selectedId === cat.id;
        return (
          <button
            key={cat.id}
            onClick={() => onSelect(cat.id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--acm-radius)] text-[12px] font-medium whitespace-nowrap transition-colors ${
              isActive
                ? 'text-[var(--acm-base)]'
                : 'text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)] hover:bg-[var(--acm-elev)]'
            }`}
            style={isActive ? { backgroundColor: cat.color } : undefined}
          >
            <span
              className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ backgroundColor: isActive ? 'rgba(255,255,255,0.6)' : cat.color }}
            />
            {cat.name}
            {cat.email_count > 0 && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded-full mono"
                style={isActive
                  ? { background: 'rgba(0,0,0,0.15)', color: 'inherit' }
                  : { background: `${cat.color}22`, color: cat.color }}
              >
                {cat.email_count}
              </span>
            )}
          </button>
        );
      })}

      {/* Manage categories */}
      <button
        onClick={onManage}
        title="Crear, editar o importar categorías"
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--acm-radius)] text-[12px] font-medium text-[var(--acm-fg-3)] border border-[var(--acm-border)] hover:text-[var(--acm-fg)] hover:border-[var(--acm-accent)] hover:bg-[var(--acm-elev)] whitespace-nowrap transition-colors ml-2"
      >
        <Settings2 size={12} />
        Gestionar
      </button>
    </div>
  );
}
