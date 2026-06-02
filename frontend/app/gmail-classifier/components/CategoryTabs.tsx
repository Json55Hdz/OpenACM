"use client";

import * as Icons from "lucide-react";
import { Plus } from "lucide-react";

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

function CategoryIcon({ iconName, color }: { iconName: string; color: string }) {
  const LucideIcon = (Icons as any)[iconName] ?? Icons.Tag;
  return <LucideIcon size={14} style={{ color }} />;
}

export function CategoryTabs({ categories, selectedId, onSelect, onManage }: CategoryTabsProps) {
  const totalCount = categories.reduce((sum, c) => sum + c.email_count, 0);

  return (
    <div className="flex items-center gap-1 px-4 py-2 border-b overflow-x-auto bg-white">
      {/* Todo tab */}
      <button
        onClick={() => onSelect(null)}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm whitespace-nowrap transition-colors ${
          selectedId === null
            ? "bg-gray-900 text-white"
            : "text-gray-600 hover:bg-gray-100"
        }`}
      >
        Todo
        {totalCount > 0 && (
          <span className={`text-xs px-1.5 rounded-full ${selectedId === null ? "bg-white/20 text-white" : "bg-gray-200 text-gray-600"}`}>
            {totalCount}
          </span>
        )}
      </button>

      {/* Category tabs */}
      {categories.map(cat => (
        <button
          key={cat.id}
          onClick={() => onSelect(cat.id)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm whitespace-nowrap transition-colors ${
            selectedId === cat.id ? "text-white" : "text-gray-600 hover:bg-gray-100"
          }`}
          style={selectedId === cat.id ? { backgroundColor: cat.color } : undefined}
        >
          <CategoryIcon iconName={cat.icon} color={selectedId === cat.id ? "white" : cat.color} />
          {cat.name}
          {cat.email_count > 0 && (
            <span
              className="text-xs px-1.5 rounded-full"
              style={{
                backgroundColor: selectedId === cat.id ? "rgba(255,255,255,0.25)" : `${cat.color}22`,
                color: selectedId === cat.id ? "white" : cat.color,
              }}
            >
              {cat.email_count}
            </span>
          )}
        </button>
      ))}

      {/* Add / manage categories */}
      <button
        onClick={onManage}
        className="flex items-center gap-1 px-2 py-1.5 rounded-full text-sm text-gray-500 hover:bg-gray-100 whitespace-nowrap ml-1"
      >
        <Plus size={14} />
        Nueva
      </button>
    </div>
  );
}
