"use client";

import { useState, useEffect } from "react";
import { X } from "lucide-react";

const API = "/api/gmail-classifier";

interface PluginSettingsProps {
  onClose: () => void;
}

function describeCron(expr: string): string {
  if (!expr) return "Desactivado";
  const map: Record<string, string> = {
    "@hourly": "Cada hora",
    "@daily": "Cada día a medianoche",
    "@midnight": "Cada día a medianoche",
    "@weekly": "Cada semana",
    "@monthly": "Cada mes",
    "0 * * * *": "Cada hora",
    "0 8 * * *": "Cada día a las 8:00am",
    "0 0 * * *": "Cada día a medianoche",
    "*/30 * * * *": "Cada 30 minutos",
    "0 9 * * 1-5": "Días hábiles a las 9am",
  };
  return map[expr.trim()] ?? `Expresión personalizada: ${expr}`;
}

export function PluginSettings({ onClose }: PluginSettingsProps) {
  const [settings, setSettings] = useState({
    auto_mark_read: "false",
    auto_apply_label: "false",
    cron_schedule: "",
    since_date_default: "",
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/settings`)
      .then(r => r.json())
      .then(data => setSettings(s => ({ ...s, ...data })))
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await fetch(`${API}/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });

      if (settings.cron_schedule) {
        await fetch(`${API}/cron`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ schedule: settings.cron_schedule }),
        });
      } else {
        await fetch(`${API}/cron`, { method: "DELETE" });
      }

      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="font-semibold text-gray-900">Configuración del Plugin</h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded">
            <X size={18} />
          </button>
        </div>

        {loading ? (
          <div className="px-6 py-8 text-center text-gray-400 text-sm">Cargando...</div>
        ) : (
          <div className="px-6 py-4 space-y-5">
            {/* Auto mark read */}
            <label className="flex items-start justify-between gap-4 cursor-pointer">
              <div>
                <p className="text-sm font-medium text-gray-800">Marcar como leído en Gmail</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  Tras clasificar, marca el correo como leído directamente en Gmail
                </p>
              </div>
              <input
                type="checkbox"
                checked={settings.auto_mark_read === "true"}
                onChange={e => setSettings(s => ({ ...s, auto_mark_read: e.target.checked ? "true" : "false" }))}
                className="w-4 h-4 mt-0.5 flex-shrink-0 accent-blue-600"
              />
            </label>

            {/* Auto apply label */}
            <label className="flex items-start justify-between gap-4 cursor-pointer">
              <div>
                <p className="text-sm font-medium text-gray-800">Aplicar etiqueta en Gmail</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  Crea y aplica en Gmail una etiqueta con el nombre de la categoría
                </p>
              </div>
              <input
                type="checkbox"
                checked={settings.auto_apply_label === "true"}
                onChange={e => setSettings(s => ({ ...s, auto_apply_label: e.target.checked ? "true" : "false" }))}
                className="w-4 h-4 mt-0.5 flex-shrink-0 accent-blue-600"
              />
            </label>

            {/* Default since date */}
            <div>
              <p className="text-sm font-medium text-gray-800 mb-1">Fecha de inicio por defecto</p>
              <p className="text-xs text-gray-500 mb-2">
                Se usa como fecha de corte cuando el cron ejecuta automáticamente
              </p>
              <input
                type="date"
                value={settings.since_date_default}
                onChange={e => setSettings(s => ({ ...s, since_date_default: e.target.value }))}
                className="w-full border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            {/* Cron schedule */}
            <div>
              <p className="text-sm font-medium text-gray-800 mb-1">Ejecución automática (cron)</p>
              <input
                type="text"
                placeholder="Ej: 0 8 * * *  (vacío = desactivado)"
                value={settings.cron_schedule}
                onChange={e => setSettings(s => ({ ...s, cron_schedule: e.target.value }))}
                className="w-full border rounded px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-gray-500 mt-1">{describeCron(settings.cron_schedule)}</p>
              <div className="flex gap-2 mt-2 flex-wrap">
                {[
                  { label: "Cada hora", value: "0 * * * *" },
                  { label: "8am diario", value: "0 8 * * *" },
                  { label: "Días hábiles 9am", value: "0 9 * * 1-5" },
                  { label: "Desactivar", value: "" },
                ].map(preset => (
                  <button
                    key={preset.label}
                    onClick={() => setSettings(s => ({ ...s, cron_schedule: preset.value }))}
                    className={`text-xs px-2 py-1 border rounded hover:bg-gray-100 transition-colors ${
                      settings.cron_schedule === preset.value ? "border-blue-400 text-blue-600 bg-blue-50" : "border-gray-200"
                    }`}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        <div className="px-6 py-4 border-t flex justify-end gap-3">
          <button onClick={onClose} className="text-sm text-gray-600 px-3 py-2 hover:bg-gray-100 rounded">
            Cancelar
          </button>
          <button
            onClick={handleSave}
            disabled={saving || loading}
            className="bg-blue-600 text-white text-sm px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50 transition-colors min-w-[90px]"
          >
            {saving ? "Guardando..." : saved ? "✓ Guardado" : "Guardar"}
          </button>
        </div>
      </div>
    </div>
  );
}
