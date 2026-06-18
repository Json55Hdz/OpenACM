'use client';

import { useProviderStatus } from '@/hooks/use-setup';
import { CheckCircle, Circle, ExternalLink } from 'lucide-react';

const ps = { configured: 'Configured', notConfigured: 'Not configured' };

export type WhatsAppMode = 'cloud_api' | 'bridge';

interface WhatsAppSetupProps {
  mode: WhatsAppMode;
  onModeChange: (mode: WhatsAppMode) => void;
  // Cloud API fields
  accessToken: string;
  onAccessTokenChange: (v: string) => void;
  phoneNumberId: string;
  onPhoneNumberIdChange: (v: string) => void;
  verifyToken: string;
  onVerifyTokenChange: (v: string) => void;
  appSecret: string;
  onAppSecretChange: (v: string) => void;
  // Bridge fields
  bridgeUrl: string;
  onBridgeUrlChange: (v: string) => void;
}

export function WhatsAppSetup({
  mode,
  onModeChange,
  accessToken,
  onAccessTokenChange,
  phoneNumberId,
  onPhoneNumberIdChange,
  verifyToken,
  onVerifyTokenChange,
  appSecret,
  onAppSecretChange,
  bridgeUrl,
  onBridgeUrlChange,
}: WhatsAppSetupProps) {
  const { data: status } = useProviderStatus();
  const isConfigured = status?.whatsapp_configured ?? false;

  return (
    <div className="space-y-4">
      {/* Header with status badge */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold" style={{ color: 'var(--acm-fg)' }}>
            WhatsApp
          </h3>
          <p className="text-sm mt-1" style={{ color: 'var(--acm-fg-3)' }}>
            {mode === 'cloud_api'
              ? 'Connect via Meta WhatsApp Business API.'
              : 'Connect via WhatsApp Web bridge (Node.js).'}
          </p>
        </div>
        {isConfigured ? (
          <span
            className="flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full"
            style={{
              color: 'var(--acm-ok)',
              background: 'oklch(0.75 0.09 160 / 0.1)',
              border: '1px solid oklch(0.75 0.09 160 / 0.25)',
            }}
          >
            <CheckCircle size={12} />
            {ps.configured}
          </span>
        ) : (
          <span
            className="flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full"
            style={{
              color: 'var(--acm-fg-4)',
              background: 'var(--acm-elev)',
              border: '1px solid var(--acm-border)',
            }}
          >
            <Circle size={12} />
            {ps.notConfigured}
          </span>
        )}
      </div>

      {/* Mode toggle */}
      <div>
        <label className="block text-sm font-medium mb-1.5" style={{ color: 'var(--acm-fg-2)' }}>
          Mode
        </label>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => onModeChange('cloud_api')}
            className="px-3 py-1.5 text-sm rounded-lg border transition-colors"
            style={
              mode === 'cloud_api'
                ? { background: 'var(--acm-accent)', color: '#fff', borderColor: 'var(--acm-accent)' }
                : { background: 'transparent', color: 'var(--acm-fg-3)', borderColor: 'var(--acm-border)' }
            }
          >
            Cloud API
          </button>
          <button
            type="button"
            onClick={() => onModeChange('bridge')}
            className="px-3 py-1.5 text-sm rounded-lg border transition-colors"
            style={
              mode === 'bridge'
                ? { background: 'var(--acm-accent)', color: '#fff', borderColor: 'var(--acm-accent)' }
                : { background: 'transparent', color: 'var(--acm-fg-3)', borderColor: 'var(--acm-border)' }
            }
          >
            Bridge
          </button>
        </div>
      </div>

      {mode === 'cloud_api' && (
        <>
          <div>
            <label className="block text-sm font-medium mb-1.5" style={{ color: 'var(--acm-fg-2)' }}>
              Access Token
            </label>
            <input
              type="password"
              value={accessToken}
              onChange={(e) => onAccessTokenChange(e.target.value)}
              placeholder="EAAx..."
              className="acm-input mono"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5" style={{ color: 'var(--acm-fg-2)' }}>
              Phone Number ID
            </label>
            <input
              type="text"
              value={phoneNumberId}
              onChange={(e) => onPhoneNumberIdChange(e.target.value)}
              placeholder="12345678901234"
              className="acm-input mono"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5" style={{ color: 'var(--acm-fg-2)' }}>
              Verify Token
            </label>
            <input
              type="text"
              value={verifyToken}
              onChange={(e) => onVerifyTokenChange(e.target.value)}
              placeholder="mi_verify_token"
              className="acm-input mono"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5" style={{ color: 'var(--acm-fg-2)' }}>
              App Secret <span style={{ color: 'var(--acm-fg-4)', fontWeight: 400 }}>(optional)</span>
            </label>
            <input
              type="password"
              value={appSecret}
              onChange={(e) => onAppSecretChange(e.target.value)}
              placeholder="aabbcc..."
              className="acm-input mono"
            />
          </div>
          <a
            href="https://developers.facebook.com/docs/whatsapp/cloud-api/get-started"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-xs transition-colors"
            style={{ color: 'var(--acm-accent)' }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = 'var(--acm-accent-hi)'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = 'var(--acm-accent)'; }}
          >
            <ExternalLink size={12} />
            WhatsApp Cloud API docs
          </a>
        </>
      )}

      {mode === 'bridge' && (
        <>
          <div>
            <label className="block text-sm font-medium mb-1.5" style={{ color: 'var(--acm-fg-2)' }}>
              Bridge URL
            </label>
            <input
              type="text"
              value={bridgeUrl}
              onChange={(e) => onBridgeUrlChange(e.target.value)}
              placeholder="http://localhost:3000"
              className="acm-input mono"
            />
          </div>
          <a
            href="https://github.com/pedroslopez/whatsapp-web.js"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-xs transition-colors"
            style={{ color: 'var(--acm-accent)' }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = 'var(--acm-accent-hi)'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = 'var(--acm-accent)'; }}
          >
            <ExternalLink size={12} />
            whatsapp-web.js docs
          </a>
        </>
      )}
    </div>
  );
}
