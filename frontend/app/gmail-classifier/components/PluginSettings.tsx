'use client';

import { useState, useEffect, useRef } from 'react';
import { X, Pencil, Trash2, Check } from 'lucide-react';

const API = '/api/gmail-classifier';

interface PluginSettingsProps {
  token: string;
  onClose: () => void;
  onAutoReplyChange?: (ids: number[]) => void;
  onAutoReplyTimeoutChange?: (timeoutSeconds: number) => void;
}

interface Category {
  id: number;
  name: string;
  color: string;
}

type ReplyExample = {
  id: number;
  category_id: number;
  subtype_label: string;
  email_context: string;
  final_response: string;
  use_count: number;
};

function describeCron(expr: string): string {
  if (!expr) return 'Desactivado';
  const map: Record<string, string> = {
    '* * * * *': 'Cada minuto',
    '*/5 * * * *': 'Cada 5 minutos',
    '*/15 * * * *': 'Cada 15 minutos',
    '*/30 * * * *': 'Cada 30 minutos',
    '@hourly': 'Cada hora',
    '0 * * * *': 'Cada hora (en punto)',
    '0 8 * * *': 'Cada día a las 8:00am',
    '0 0 * * *': 'Cada día a medianoche',
    '0 9 * * 1-5': 'Días hábiles a las 9am',
  };
  return map[expr.trim()] ?? `Expresión: ${expr}`;
}

const CRON_PRESETS = [
  { label: 'Cada minuto', value: '* * * * *' },
  { label: 'Cada 5 min', value: '*/5 * * * *' },
  { label: 'Cada hora', value: '0 * * * *' },
  { label: '8am diario', value: '0 8 * * *' },
  { label: 'Desactivar', value: '' },
];

type MainTab = 'general' | 'auto-respuesta' | 'backup';

export function PluginSettings({ token, onClose, onAutoReplyChange, onAutoReplyTimeoutChange }: PluginSettingsProps) {
  const [activeTab, setActiveTab] = useState<MainTab>('general');

  const [settings, setSettings] = useState({
    auto_mark_read: 'false',
    auto_apply_label: 'false',
    cron_schedule: '',
    since_date_default: '',
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(true);
  const [applyingRetro, setApplyingRetro] = useState(false);

  // Auto-respuesta state
  const [categories, setCategories] = useState<Category[]>([]);
  const [autoReplyCats, setAutoReplyCats] = useState<number[]>([]);
  const [autoReplyTimeout, setAutoReplyTimeout] = useState<number>(60);
  const [exampleFilter, setExampleFilter] = useState<number | null>(null);
  const [examples, setExamples] = useState<ReplyExample[]>([]);
  const [loadingExamples, setLoadingExamples] = useState(false);
  const [editingExample, setEditingExample] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<{ subtype_label: string; final_response: string }>({
    subtype_label: '',
    final_response: '',
  });

  // Backup tab state
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{
    categories_updated: number;
    categories_created: number;
    examples_added: number;
    settings_updated: number;
  } | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  // Load settings + categories on mount
  useEffect(() => {
    fetch(`${API}/settings`, { headers })
      .then(r => r.json())
      .then(data => {
        setSettings(s => ({ ...s, ...data }));
        const cats = data?.autoreply_enabled_categories;
        if (cats) {
          try {
            const parsed = JSON.parse(cats);
            if (Array.isArray(parsed)) setAutoReplyCats(parsed);
          } catch { /* ignore */ }
        }
        const timeoutSecs = parseInt(data?.autoreply_timeout_seconds ?? '60', 10);
        if (!isNaN(timeoutSecs) && timeoutSecs > 0) setAutoReplyTimeout(timeoutSecs);
      })
      .finally(() => setLoading(false));

    fetch(`${API}/categories`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data)) setCategories(data);
      })
      .catch(() => {/* ignore */});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch reply examples when filter or active tab changes
  useEffect(() => {
    if (activeTab !== 'auto-respuesta') return;
    setLoadingExamples(true);
    const url = exampleFilter
      ? `${API}/reply-examples?category_id=${exampleFilter}`
      : `${API}/reply-examples`;
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data)) setExamples(data);
        else setExamples([]);
      })
      .catch(() => setExamples([]))
      .finally(() => setLoadingExamples(false));
  }, [exampleFilter, activeTab]); // eslint-disable-line react-hooks/exhaustive-deps

  const saveKey = async (key: string, value: string) => {
    const res = await fetch(`${API}/settings`, {
      method: 'PUT', headers,
      body: JSON.stringify({ [key]: value }),
    });
    if (res.ok) {
      if (value === 'true' && (key === 'auto_mark_read' || key === 'auto_apply_label')) {
        setApplyingRetro(true);
        setTimeout(() => setApplyingRetro(false), 8000);
      }
    }
  };

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

  async function toggleCategory(categoryId: number) {
    const next = autoReplyCats.includes(categoryId)
      ? autoReplyCats.filter(id => id !== categoryId)
      : [...autoReplyCats, categoryId];
    const prev = autoReplyCats;
    const nextStr = JSON.stringify(next);
    setAutoReplyCats(next);
    setSettings(s => ({ ...s, autoreply_enabled_categories: nextStr }));
    try {
      await fetch(`${API}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ autoreply_enabled_categories: nextStr }),
      });
      onAutoReplyChange?.(next);
    } catch {
      setAutoReplyCats(prev); // rollback on failure
      setSettings(s => ({ ...s, autoreply_enabled_categories: JSON.stringify(prev) }));
    }
  }

  async function saveTimeout(secs: number) {
    if (isNaN(secs) || secs < 5) return;
    try {
      await fetch(`${API}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ autoreply_timeout_seconds: secs }),
      });
      onAutoReplyTimeoutChange?.(secs);
    } catch { /* ignore */ }
  }

  async function handleExport() {
    setExportError(null);
    setExporting(true);
    try {
      const res = await fetch(`${API}/export`, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) {
        setExportError('Error al exportar la configuración');
        return;
      }
      const blob = await res.blob();
      const today = new Date().toISOString().slice(0, 10);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `gmail-classifier-backup-${today}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null;
    setSelectedFile(file);
    setImportResult(null);
    setImportError(null);
  }

  async function handleImport() {
    if (!selectedFile) return;
    setImporting(true);
    setImportResult(null);
    setImportError(null);
    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      const res = await fetch(`${API}/import`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      if (res.ok) {
        setImportResult(await res.json());
        setSelectedFile(null);
        if (fileInputRef.current) fileInputRef.current.value = '';
      } else {
        const err = await res.json().catch(() => ({}));
        setImportError(err.detail || 'Error al importar el archivo');
      }
    } catch {
      setImportError('Error de red al importar');
    } finally {
      setImporting(false);
    }
  }

  const TABS: { id: MainTab; label: string }[] = [
    { id: 'general', label: 'General' },
    { id: 'auto-respuesta', label: 'Auto-respuesta' },
    { id: 'backup', label: 'Backup' },
  ];

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-[var(--acm-base)] border border-[var(--acm-border)] rounded-[var(--acm-radius)] w-full max-w-lg shadow-2xl flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--acm-border)] flex-shrink-0">
          <div>
            <span className="acm-breadcrumb">/ gmail / configuración</span>
            <h2 className="text-[15px] font-semibold text-[var(--acm-fg)]">Configuración del Plugin</h2>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-[var(--acm-elev)] rounded text-[var(--acm-fg-3)]">
            <X size={16} />
          </button>
        </div>

        {/* Tab bar */}
        <div className="flex border-b border-[var(--acm-border)] px-5 flex-shrink-0">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`text-[12px] px-3 py-2.5 -mb-px border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-[var(--acm-accent)] text-[var(--acm-accent)] font-medium'
                  : 'border-transparent text-[var(--acm-fg-3)] hover:text-[var(--acm-fg)]'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="px-5 py-8 text-center text-[var(--acm-fg-4)] text-[12px]">Cargando…</div>
        ) : (
          <div className="overflow-y-auto flex-1">
            {/* ── General tab ── */}
            {activeTab === 'general' && (
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
                    onClick={async () => {
                      const next = settings.auto_mark_read === 'true' ? 'false' : 'true';
                      setSettings(s => ({ ...s, auto_mark_read: next }));
                      await saveKey('auto_mark_read', next);
                    }}
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
                    onClick={async () => {
                      const next = settings.auto_apply_label === 'true' ? 'false' : 'true';
                      setSettings(s => ({ ...s, auto_apply_label: next }));
                      await saveKey('auto_apply_label', next);
                    }}
                    className={`w-9 h-5 rounded-full transition-colors flex-shrink-0 mt-0.5 relative cursor-pointer ${
                      settings.auto_apply_label === 'true' ? 'bg-[var(--acm-accent)]' : 'bg-[var(--acm-elev)]'
                    }`}
                  >
                    <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                      settings.auto_apply_label === 'true' ? 'translate-x-4' : 'translate-x-0.5'
                    }`} />
                  </div>
                </label>

                {/* Retroactive indicator */}
                {applyingRetro && (
                  <div className="flex items-center gap-2 text-[11px] text-[var(--acm-accent)] acm-pulse">
                    <span className="dot dot-accent" />
                    Aplicando a correos ya clasificados…
                  </div>
                )}

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

            {/* ── Auto-respuesta tab ── */}
            {activeTab === 'auto-respuesta' && (
              <div className="px-5 py-4 space-y-6">
                {/* Section 1: Activación por categoría */}
                <div>
                  <h3 className="text-[13px] font-semibold text-[var(--acm-fg)] mb-3">Activación por categoría</h3>
                  <p className="text-[11px] text-[var(--acm-fg-4)] mb-3">
                    Activa la sugerencia automática de respuestas para cada categoría. Desactivado por defecto.
                  </p>
                  {categories.length === 0 ? (
                    <p className="text-[11px] text-[var(--acm-fg-4)]">No hay categorías configuradas.</p>
                  ) : (
                    <div className="space-y-3">
                      {categories.map(cat => (
                        <div key={cat.id} className="flex items-center justify-between">
                          <span className="text-[13px] text-[var(--acm-fg)]">{cat.name}</span>
                          <button
                            onClick={() => toggleCategory(cat.id)}
                            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                              autoReplyCats.includes(cat.id)
                                ? 'bg-[var(--acm-accent)]'
                                : 'bg-[var(--acm-elev)]'
                            }`}
                            aria-label={`Toggle auto-reply for ${cat.name}`}
                          >
                            <span
                              className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                                autoReplyCats.includes(cat.id) ? 'translate-x-4' : 'translate-x-0.5'
                              }`}
                            />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Timeout setting */}
                <div className="mt-4 flex items-center justify-between">
                  <div>
                    <span className="text-[13px] text-[var(--acm-fg)]">Tiempo de espera (segundos)</span>
                    <p className="text-[11px] text-[var(--acm-fg-4)] mt-0.5">Tiempo máximo para generar una sugerencia</p>
                  </div>
                  <input
                    type="number"
                    min={5}
                    max={300}
                    value={autoReplyTimeout}
                    onChange={e => setAutoReplyTimeout(Number(e.target.value))}
                    onBlur={e => saveTimeout(Number(e.target.value))}
                    className="w-20 text-center bg-[var(--acm-elev)] border border-[var(--acm-border)] text-[var(--acm-fg)] text-[13px] rounded-[var(--acm-radius)] px-2 py-1 outline-none focus:border-[var(--acm-accent)]"
                  />
                </div>

                <div className="acm-rule" />

                {/* Section 2: Ejemplos aprendidos */}
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-[13px] font-semibold text-[var(--acm-fg)]">Ejemplos aprendidos</h3>
                    <select
                      value={exampleFilter ?? ''}
                      onChange={e => setExampleFilter(e.target.value ? Number(e.target.value) : null)}
                      className="text-[11px] border border-[var(--acm-border)] rounded px-2 py-1 bg-[var(--acm-base)] text-[var(--acm-fg)]"
                    >
                      <option value="">Todas las categorías</option>
                      {categories.map(cat => (
                        <option key={cat.id} value={cat.id}>{cat.name}</option>
                      ))}
                    </select>
                  </div>

                  {loadingExamples ? (
                    <p className="text-[11px] text-[var(--acm-fg-4)]">Cargando…</p>
                  ) : examples.length === 0 ? (
                    <p className="text-[11px] text-[var(--acm-fg-4)]">No hay ejemplos aprendidos aún.</p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-[11px]">
                        <thead>
                          <tr className="text-left text-[var(--acm-fg-3)] border-b border-[var(--acm-border)]">
                            <th className="pb-2 pr-3 font-medium">Subtipo</th>
                            <th className="pb-2 pr-3 font-medium">Correo (fragmento)</th>
                            <th className="pb-2 pr-3 font-medium">Respuesta</th>
                            <th className="pb-2 pr-3 text-center font-medium">Usos</th>
                            <th className="pb-2" />
                          </tr>
                        </thead>
                        <tbody>
                          {examples.map(ex => (
                            <tr key={ex.id} className="border-b border-[var(--acm-border)] last:border-0">
                              <td className="py-2 pr-3 align-top">
                                {editingExample === ex.id ? (
                                  <input
                                    value={editDraft.subtype_label}
                                    onChange={e => setEditDraft(d => ({ ...d, subtype_label: e.target.value }))}
                                    className="text-[11px] border border-[var(--acm-border)] rounded px-1 w-full bg-[var(--acm-base)] text-[var(--acm-fg)]"
                                  />
                                ) : (
                                  <span className="text-[var(--acm-fg-3)]">{ex.subtype_label || '—'}</span>
                                )}
                              </td>
                              <td className="py-2 pr-3 align-top max-w-[120px]">
                                <span className="text-[var(--acm-fg-4)] line-clamp-2 block">
                                  {ex.email_context.slice(0, 80)}
                                </span>
                              </td>
                              <td className="py-2 pr-3 align-top max-w-[140px]">
                                {editingExample === ex.id ? (
                                  <textarea
                                    value={editDraft.final_response}
                                    onChange={e => setEditDraft(d => ({ ...d, final_response: e.target.value }))}
                                    rows={2}
                                    className="text-[11px] border border-[var(--acm-border)] rounded px-1 w-full bg-[var(--acm-base)] text-[var(--acm-fg)]"
                                  />
                                ) : (
                                  <span className="text-[var(--acm-fg-4)] line-clamp-2 block">
                                    {ex.final_response.slice(0, 100)}
                                  </span>
                                )}
                              </td>
                              <td className="py-2 pr-3 align-top text-center text-[var(--acm-fg-4)]">
                                {ex.use_count}
                              </td>
                              <td className="py-2 align-top">
                                <div className="flex gap-1">
                                  {editingExample === ex.id ? (
                                    <>
                                      <button
                                        onClick={async () => {
                                          try {
                                            const res = await fetch(`${API}/reply-examples/${ex.id}`, {
                                              method: 'PUT',
                                              headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                                              body: JSON.stringify(editDraft),
                                            });
                                            if (res.ok) {
                                              setExamples(prev =>
                                                prev.map(e => e.id === ex.id ? { ...e, ...editDraft } : e)
                                              );
                                              setEditingExample(null);
                                            }
                                            // If not ok, stay in edit mode — don't update local state
                                          } catch {
                                            // Network error — stay in edit mode
                                          }
                                        }}
                                        className="p-1 text-green-500 hover:text-green-400"
                                        title="Guardar"
                                        aria-label="Guardar"
                                      >
                                        <Check size={13} />
                                      </button>
                                      <button
                                        onClick={() => setEditingExample(null)}
                                        className="p-1 text-[var(--acm-fg-4)] hover:text-[var(--acm-fg-3)]"
                                        title="Cancelar edición"
                                        aria-label="Cancelar edición"
                                      >
                                        <X size={13} />
                                      </button>
                                    </>
                                  ) : (
                                    <>
                                      <button
                                        onClick={() => {
                                          setEditingExample(ex.id);
                                          setEditDraft({
                                            subtype_label: ex.subtype_label,
                                            final_response: ex.final_response,
                                          });
                                        }}
                                        className="p-1 text-[var(--acm-fg-4)] hover:text-[var(--acm-fg-3)]"
                                        title="Editar"
                                        aria-label="Editar"
                                      >
                                        <Pencil size={13} />
                                      </button>
                                      <button
                                        onClick={async () => {
                                          try {
                                            const res = await fetch(`${API}/reply-examples/${ex.id}`, {
                                              method: 'DELETE',
                                              headers: { Authorization: `Bearer ${token}` },
                                            });
                                            if (res.ok) {
                                              setExamples(prev => prev.filter(e => e.id !== ex.id));
                                            }
                                          } catch {
                                            // Network error — keep the row
                                          }
                                        }}
                                        className="p-1 text-red-400 hover:text-red-500"
                                        title="Eliminar"
                                        aria-label="Eliminar"
                                      >
                                        <Trash2 size={13} />
                                      </button>
                                    </>
                                  )}
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* ── Backup tab ── */}
            {activeTab === 'backup' && (
              <div className="px-5 py-4 space-y-6">
                {/* Export */}
                <div>
                  <h3 className="text-[13px] font-semibold text-[var(--acm-fg)] mb-1">Exportar configuración</h3>
                  <p className="text-[11px] text-[var(--acm-fg-4)] mb-3">
                    Descarga un archivo JSON con tus categorías, settings y ejemplos de respuesta aprendidos.
                  </p>
                  <button
                    onClick={handleExport}
                    disabled={exporting}
                    className="btn-secondary text-[12px] py-[7px] px-3 min-w-[170px]"
                  >
                    {exporting ? 'Descargando…' : 'Descargar configuración'}
                  </button>
                  {exportError && (
                    <p className="mt-2 text-[12px] text-red-400">{exportError}</p>
                  )}
                </div>

                <div className="acm-rule" />

                {/* Import */}
                <div>
                  <h3 className="text-[13px] font-semibold text-[var(--acm-fg)] mb-1">Importar configuración</h3>
                  <p className="text-[11px] text-[var(--acm-fg-4)] mb-3">
                    Combina un backup con tu configuración actual. Las categorías existentes se actualizan
                    por nombre; los ejemplos nuevos se agregan sin duplicar.
                  </p>

                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".json"
                    className="hidden"
                    onChange={handleFileSelect}
                  />

                  {!selectedFile ? (
                    <button
                      onClick={() => fileInputRef.current?.click()}
                      className="btn-secondary text-[12px] py-[7px] px-3"
                    >
                      Seleccionar archivo…
                    </button>
                  ) : (
                    <div className="space-y-3">
                      <p className="text-[12px] text-[var(--acm-fg-3)]">
                        Archivo: <span className="font-medium">{selectedFile.name}</span>
                      </p>
                      <div className="flex gap-2">
                        <button
                          onClick={handleImport}
                          disabled={importing}
                          className="btn-primary text-[12px] py-[7px] px-3 min-w-[150px]"
                        >
                          {importing ? 'Importando…' : 'Confirmar importación'}
                        </button>
                        <button
                          onClick={() => { setSelectedFile(null); setImportResult(null); setImportError(null); if (fileInputRef.current) fileInputRef.current.value = ''; }}
                          className="btn-secondary text-[12px] py-[7px] px-3"
                        >
                          Cancelar
                        </button>
                      </div>
                    </div>
                  )}

                  {importResult && (
                    <div className="mt-4 rounded p-3 bg-[var(--acm-elev)] border border-[var(--acm-border)] text-[12px]">
                      <p className="font-medium text-[var(--acm-fg)] mb-2">✓ Importación completa</p>
                      <ul className="space-y-1 text-[var(--acm-fg-3)]">
                        <li>• {importResult.categories_updated} categorías actualizadas, {importResult.categories_created} creadas</li>
                        <li>• {importResult.examples_added} ejemplos de respuesta agregados</li>
                        <li>• {importResult.settings_updated} settings actualizados</li>
                      </ul>
                    </div>
                  )}

                  {importError && (
                    <p className="mt-3 text-[12px] text-red-400">{importError}</p>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Footer — only show Save button on General tab */}
        <div className="px-5 py-4 border-t border-[var(--acm-border)] flex justify-end gap-2 flex-shrink-0">
          <button onClick={onClose} className="btn-secondary text-[12px] py-[7px] px-3">
            Cancelar
          </button>
          {activeTab === 'general' && (
            <button
              onClick={handleSave}
              disabled={saving || loading}
              className="btn-primary text-[12px] py-[7px] px-3 min-w-[90px]"
            >
              {saving ? 'Guardando…' : saved ? '✓ Guardado' : 'Guardar'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
