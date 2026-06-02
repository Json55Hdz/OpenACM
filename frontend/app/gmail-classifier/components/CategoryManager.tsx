"use client";

import { useState } from "react";
import { X, Plus, Trash2, Edit2 } from "lucide-react";

const API = "/api/gmail-classifier";

const PRESET_COLORS = [
  "#6366f1", "#3b82f6", "#10b981", "#f59e0b",
  "#ef4444", "#8b5cf6", "#ec4899", "#6b7280",
];

const PRESET_ICONS = [
  "Tag", "Mail", "Car", "FileText", "Inbox",
  "Briefcase", "Home", "Star", "Bell", "Users",
  "ShoppingCart", "Calendar", "Map", "Truck", "Landmark",
];

interface Category {
  id: number;
  name: string;
  description: string;
  color: string;
  icon: string;
}

interface FormState {
  name: string;
  description: string;
  color: string;
  icon: string;
}

interface CategoryManagerProps {
  categories: Category[];
  onClose: () => void;
  onSaved: () => void;
}

export function CategoryManager({ categories, onClose, onSaved }: CategoryManagerProps) {
  const [editingId, setEditingId] = useState<number | "new" | null>(null);
  const [form, setForm] = useState<FormState>({ name: "", description: "", color: "#6366f1", icon: "Tag" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const startNew = () => {
    setForm({ name: "", description: "", color: "#6366f1", icon: "Tag" });
    setEditingId("new");
    setError("");
  };

  const startEdit = (cat: Category) => {
    setForm({ name: cat.name, description: cat.description, color: cat.color, icon: cat.icon });
    setEditingId(cat.id);
    setError("");
  };

  const handleSave = async () => {
    if (!form.name.trim()) { setError("El nombre es requerido"); return; }
    setSaving(true);
    setError("");
    try {
      const url = editingId === "new" ? `${API}/categories` : `${API}/categories/${editingId}`;
      const method = editingId === "new" ? "POST" : "PUT";
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const e = await res.json();
        setError(e.detail || "Error al guardar");
        return;
      }
      onSaved();
      setEditingId(null);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("¿Eliminar esta categoría? Los correos pasarán a 'Otros'.")) return;
    await fetch(`${API}/categories/${id}`, { method: "DELETE" });
    onSaved();
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="font-semibold text-gray-900">Gestionar Categorías</h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded">
            <X size={18} />
          </button>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-2">
          {categories.map(cat => (
            <div key={cat.id} className="border rounded-lg overflow-hidden">
              {editingId === cat.id ? (
                <CategoryForm
                  form={form}
                  onChange={setForm}
                  onSave={handleSave}
                  onCancel={() => setEditingId(null)}
                  saving={saving}
                  error={error}
                />
              ) : (
                <div className="flex items-center gap-3 px-4 py-3">
                  <div className="w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: cat.color }} />
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-sm text-gray-800">{cat.name}</p>
                    {cat.description && (
                      <p className="text-xs text-gray-500 truncate">{cat.description}</p>
                    )}
                  </div>
                  {cat.name !== "Otros" && (
                    <div className="flex gap-1">
                      <button
                        onClick={() => startEdit(cat)}
                        className="p-1.5 hover:bg-gray-100 rounded text-gray-400 hover:text-gray-700"
                      >
                        <Edit2 size={14} />
                      </button>
                      <button
                        onClick={() => handleDelete(cat.id)}
                        className="p-1.5 hover:bg-red-50 rounded text-gray-400 hover:text-red-600"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {editingId === "new" && (
            <div className="border rounded-lg overflow-hidden border-blue-200">
              <CategoryForm
                form={form}
                onChange={setForm}
                onSave={handleSave}
                onCancel={() => setEditingId(null)}
                saving={saving}
                error={error}
              />
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t">
          <button
            onClick={startNew}
            disabled={editingId !== null}
            className="flex items-center gap-2 text-sm text-blue-600 hover:text-blue-800 disabled:opacity-40"
          >
            <Plus size={16} /> Agregar categoría
          </button>
        </div>
      </div>
    </div>
  );
}

function CategoryForm({
  form,
  onChange,
  onSave,
  onCancel,
  saving,
  error,
}: {
  form: FormState;
  onChange: (f: FormState) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  error: string;
}) {
  return (
    <div className="px-4 py-3 space-y-3 bg-gray-50">
      <input
        className="w-full border rounded px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        placeholder="Nombre de la categoría *"
        value={form.name}
        onChange={e => onChange({ ...form, name: e.target.value })}
      />
      <textarea
        className="w-full border rounded px-3 py-2 text-sm resize-none bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        placeholder="Descripción (ayuda a la IA a clasificar mejor)"
        rows={2}
        value={form.description}
        onChange={e => onChange({ ...form, description: e.target.value })}
      />
      <div>
        <p className="text-xs text-gray-500 mb-1.5">Color</p>
        <div className="flex gap-2 flex-wrap">
          {PRESET_COLORS.map(c => (
            <button
              key={c}
              onClick={() => onChange({ ...form, color: c })}
              className={`w-6 h-6 rounded-full border-2 transition-transform ${form.color === c ? "border-gray-900 scale-110" : "border-transparent"}`}
              style={{ backgroundColor: c }}
            />
          ))}
        </div>
      </div>
      <div>
        <p className="text-xs text-gray-500 mb-1.5">Icono</p>
        <div className="flex gap-1.5 flex-wrap">
          {PRESET_ICONS.map(icon => (
            <button
              key={icon}
              onClick={() => onChange({ ...form, icon })}
              className={`px-2 py-1 text-xs border rounded transition-colors ${
                form.icon === icon ? "bg-gray-900 text-white border-gray-900" : "hover:bg-gray-100 border-gray-200"
              }`}
            >
              {icon}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
      <div className="flex gap-2">
        <button
          onClick={onSave}
          disabled={saving}
          className="bg-blue-600 text-white text-sm px-3 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Guardando..." : "Guardar"}
        </button>
        <button
          onClick={onCancel}
          className="text-sm text-gray-600 px-3 py-1.5 rounded hover:bg-gray-200"
        >
          Cancelar
        </button>
      </div>
    </div>
  );
}
