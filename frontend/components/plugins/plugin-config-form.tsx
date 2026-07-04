'use client';

import { useState, useEffect } from 'react';
import { usePluginConfig, useSavePluginConfig } from '@/hooks/use-plugins';
import { Loader2 } from 'lucide-react';

export function PluginConfigForm({
  pluginName,
  onSaved,
}: {
  pluginName: string;
  onSaved?: () => void;
}) {
  const { data, isLoading } = usePluginConfig(pluginName);
  const saveConfig = useSavePluginConfig(pluginName);
  const [values, setValues] = useState<Record<string, string>>({});

  useEffect(() => {
    if (data?.values) setValues(data.values);
  }, [data]);

  if (isLoading || !data) {
    return <Loader2 size={20} className="animate-spin" style={{ color: 'var(--acm-fg-4)' }} />;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await saveConfig.mutateAsync(values);
    onSaved?.();
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {data.schema.map((field) => (
        <div key={field.key}>
          <label className="label" style={{ display: 'block', marginBottom: 6 }}>
            {field.label}
            {field.required && <span style={{ color: 'var(--acm-err)' }}> *</span>}
          </label>
          {field.type === 'boolean' ? (
            <input
              type="checkbox"
              checked={values[field.key] === 'true'}
              onChange={(e) =>
                setValues((v) => ({ ...v, [field.key]: e.target.checked ? 'true' : 'false' }))
              }
            />
          ) : (
            <input
              type={field.type === 'password' ? 'password' : field.type === 'number' ? 'number' : 'text'}
              value={values[field.key] ?? ''}
              onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
              placeholder={field.help}
              className="acm-input"
              required={field.required}
            />
          )}
          {field.help && (
            <p style={{ fontSize: 12, color: 'var(--acm-fg-4)', marginTop: 4 }}>{field.help}</p>
          )}
        </div>
      ))}
      <button type="submit" disabled={saveConfig.isPending} className="btn-primary">
        {saveConfig.isPending ? <Loader2 size={16} className="animate-spin" /> : 'Guardar'}
      </button>
    </form>
  );
}
