'use client';

import { useState, useEffect } from 'react';
import { X } from 'lucide-react';

const API = '/api/gmail-classifier';

interface PluginSettingsProps {
  token: string;
  onClose: () => void;
}

function describeCron(expr: string): string {
  if (!expr) return 'Desactivado';
  const map: Record<string, string> = {
    '@hourly': 'Cada hora',
    '@daily': 'Cada día a medianoche',
    '0 * * * *': 'Cada hora (en punto)',
    '0 8 * * *': 'Cada día a las 8:00am',
    '0 0 * * *': 'Cada día a medianoche',
    '*/30 * * * *': 'Cada 30 minutos',
    '0 9 * * 1-5': 'Días hábiles a las 9am',
  };
  return map[expr.trim()] ?? `Expresión: ${expr}`;
}

const CRON_PRESETS = [
  { label: 'Cada hora', value: '0 * * * *' },
  { label: '8am diario', value: '0 8 * * *' },
  { label: 'Días hábiles 9am', value: '0 9 * * 1-5' },
  { label: 'Desactivar', value: '' },
];

export function PluginSettings({ token, onClose }: PluginSettingsProps) {
  const [settings, setSettings] = useState({
    auto_mark_read: 'false',
    auto_apply_label: 'false',
    cron_schedule: '',
    since_date_default: '',
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(true);

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  useEffect(() => {
    fetch(`${API}/settings`, { headers })
      .then(r => r.json())
      .then(data => setSettings(s => ({ ...s, ...data })))
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSave = async () => {
    setSaving(true);
    try {
      await fetch(`${API}/settings`, {
        method: 'PUT',
        headers,
        body: JSON.stringify(settings),
      });

      if (settings.cron_schedule) {
        await fetch(`${API}/cron`, {
          method: 'POST',
          headers,
          body: JSON.stringify({ schedule: settings.cron_schedule }),
        });
      } else {
        await fetch(`${API}/cron`, { method: 'DELETE', headers });
      }

      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-[var(--acm-base)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--acm-border)]">
          <div>
            <span className="acm-breadcrumb">/ gmail / configuración</span>
            <h2 className="text-[15px] font-semibold text-[var(--acm-fg)]">Configuración del Plugin</h2>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-[var(--acm-elev)] rounded text-[var(--acm-fg-3)]">
            <X size={16} />
          </button>
        </div>

        {loading ? (
          <div className="px-5 py-8 text-center text-[var(--acm-fg-4)] text-[12px]">Cargando…</div>
        ) : (
          <div className="px-5 py-4 space-y-5">
            {/* Toggle: auto_mark_read */}
            <label className="flex items-start justify-between gap-4 cursor-pointer">
              <div>
                <p className="text-[13px] font-medium text-[var(--acm-fg)]">Marcar como leído en Gmail</p>
                <p className="text-[11px] text-[var(--acm-fg-4)] mt-0.5">
                  Tras clasificar, marca el correo como leído directamente en Gmail
                </p>
              </div>
              <div
                onClick={() => setSettings(s => ({ ...s, auto_mark_read: s.auto_mark_read === 'true' ? 'false' : 'true' }))}
                className={`w-9 h-5 rounded-full transition-colors flex-shrink-0 mt-0.5 relative cursor-pointer ${
                  settings.auto_mark_read === 'true' ? 'bg-[var(--acm-accent)]' : 'bg-[var(--acm-elev)]'
                }`}
              >
                <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                  settings.auto_mark_read === 'true' ? 'translate-x-4' : 'translate-x-0.5'
                }`} />
              </div>
            </label>

            <div className="acm-rule" />

            {/* Toggle: auto_apply_label */}
            <label className="flex items-start justify-between gap-4 cursor-pointer">
              <div>
                <p className="text-[13px] font-medium text-[var(--acm-fg)]">Aplicar etiqueta en Gmail</p>
                <p className="text-[11px] text-[var(--acm-fg-4)] mt-0.5">
                  Crea y aplica una etiqueta con el nombre de la categoría en Gmail
                </p>
              </div>
              <div
                onClick={() => setSettings(s => ({ ...s, auto_apply_label: s.auto_apply_label === 'true' ? 'false' : 'true' }))}
                className={`w-9 h-5 rounded-full transition-colors flex-shrink-0 mt-0.5 relative cursor-pointer ${
                  settings.auto_apply_label === 'true' ? 'bg-[var(--acm-accent)]' : 'bg-[var(--acm-elev)]'
                }`}
              >
                <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                  settings.auto_apply_label === 'true' ? 'translate-x-4' : 'translate-x-0.5'
                }`} />
              </div>
            </label>

            <div className="acm-rule" />

            {/* Since date default */}
            <div>
              <label className="label block mb-2">Fecha de inicio por defecto</label>
              <input
                type="date"
                value={settings.since_date_default}
                onChange={e => setSettings(s => ({ ...s, since_date_default: e.target.value }))}
                className="acm-input text-[13px]"
              />
              <p className="text-[11px] text-[var(--acm-fg-4)] mt-1">
                Usada cuando el cron ejecuta automáticamente
              </p>
            </div>

            <div className="acm-rule" />

            {/* Cron schedule */}
            <div>
              <label className="label block mb-2">Ejecución automática</label>
              <input
                type="text"
                placeholder="Ej: 0 8 * * *  (vacío = desactivado)"
                value={settings.cron_schedule}
                onChange={e => setSettings(s => ({ ...s, cron_schedule: e.target.value }))}
                className="acm-input mono text-[12px]"
              />
              <p className="text-[11px] text-[var(--acm-fg-4)] mt-1">{describeCron(settings.cron_schedule)}</p>
              <div className="flex gap-1.5 mt-2 flex-wrap">
                {CRON_PRESETS.map(preset => (
                  <button
                    key={preset.label}
                    onClick={() => setSettings(s => ({ ...s, cron_schedule: preset.value }))}
                    className={`text-[11px] px-2 py-1 rounded transition-colors border ${
                      settings.cron_schedule === preset.value
                        ? 'border-[var(--acm-accent)] text-[var(--acm-accent)] bg-[var(--acm-accent-tint)]'
                        : 'border-[var(--acm-border)] text-[var(--acm-fg-3)] hover:border-[var(--acm-border-strong)]'
                    }`}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        <div className="px-5 py-4 border-t border-[var(--acm-border)] flex justify-end gap-2">
          <button onClick={onClose} className="btn-secondary text-[12px] py-[7px] px-3">
            Cancelar
          </button>
          <button
            onClick={handleSave}
            disabled={saving || loading}
            className="btn-primary text-[12px] py-[7px] px-3 min-w-[90px]"
          >
            {saving ? 'Guardando…' : saved ? '✓ Guardado' : 'Guardar'}
          </button>
        </div>
      </div>
    </div>
  );
}
