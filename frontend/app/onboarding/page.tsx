'use client';

import { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/hooks/use-websocket';
import { useConfigStatus, useSaveSetup, useSetModel, useGoogleStatus, useSaveGoogleCredentials, useStartGoogleAuth } from '@/hooks/use-setup';
import { ProviderSetupForm } from '@/components/setup/provider-setup-form';
import { ModelSelector } from '@/components/setup/model-selector';
import { TelegramSetup } from '@/components/setup/telegram-setup';
import { useAddCustomProvider, useCustomProviders } from '@/hooks/use-setup';
import { translations } from '@/lib/translations';
import { ACMMark } from '@/components/ui/acm-mark';
import {
  ArrowRight,
  ArrowLeft,
  CheckCircle,
  Shield,
  Zap,
  Lock,
  Loader2,
  Rocket,
  Globe2,
  ChevronsRight,
  Plus,
  Server,
  X,
} from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { toast } from 'sonner';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const t = translations.onboarding;

const STEPS = [
  { number: 1, title: t.steps.auth, description: t.steps.authDesc },
  { number: 2, title: t.steps.providers, description: t.steps.providersDesc },
  { number: 3, title: t.steps.modelTelegram, description: t.steps.modelTelegramDesc },
  { number: 4, title: 'Google Services', description: 'Optional — Gmail, Calendar, Drive' },
  { number: 5, title: t.steps.ready, description: t.steps.readyDesc },
];

function StepIndicator({
  step,
  isActive,
  isCompleted,
}: {
  step: (typeof STEPS)[number];
  isActive: boolean;
  isCompleted: boolean;
}) {
  return (
    <div
      style={
        isActive
          ? {
              background: 'var(--acm-accent-soft)',
              border: '1px solid oklch(0.84 0.16 82 / 0.18)',
              boxShadow: 'inset 2px 0 0 var(--acm-accent)',
            }
          : {
              background: 'transparent',
              border: '1px solid transparent',
            }
      }
      className="flex items-start gap-3 px-4 py-3 rounded-lg transition-all"
    >
      <div
        style={
          isCompleted
            ? { background: 'var(--acm-ok)' }
            : isActive
              ? { background: 'var(--acm-accent)' }
              : { background: 'var(--acm-elev)' }
        }
        className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 font-semibold text-xs"
        // color handled inline below via children
      >
        {isCompleted ? (
          <CheckCircle size={14} style={{ color: 'oklch(0.18 0.015 80)' }} />
        ) : (
          <span
            style={{
              color: isActive ? 'oklch(0.18 0.015 80)' : 'var(--acm-fg-4)',
            }}
          >
            {step.number}
          </span>
        )}
      </div>
      <div>
        <h3
          className="font-medium text-sm"
          style={{ color: isActive ? 'var(--acm-fg)' : 'var(--acm-fg-3)' }}
        >
          {step.title}
        </h3>
        <p className="text-xs mt-0.5" style={{ color: 'var(--acm-fg-4)' }}>
          {step.description}
        </p>
      </div>
    </div>
  );
}

function OnboardingContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const forceOpen = searchParams.get('force') === 'true';
  const { login, isAuthenticated } = useAuth();
  const { data: configStatus } = useConfigStatus();
  const saveSetup = useSaveSetup();
  const setModel = useSetModel();

  const [currentStep, setCurrentStep] = useState(1);
  const [token, setToken] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [selectedProvider, setSelectedProvider] = useState<string | undefined>();
  const [telegramToken, setTelegramToken] = useState('');
  const [googleCredJson, setGoogleCredJson] = useState('');
  const { data: googleStatus } = useGoogleStatus();
  const saveGoogleCreds = useSaveGoogleCredentials();
  const startGoogleAuth = useStartGoogleAuth();

  // Custom provider form state (wizard step 2)
  const addCustomProvider = useAddCustomProvider();
  const { data: customProviders = [] } = useCustomProviders();
  const [showCustomForm, setShowCustomForm] = useState(false);
  const [cpForm, setCpForm] = useState({ name: '', base_url: '', api_key: '', default_model: '' });

  const handleAddCustomProvider = async () => {
    if (!cpForm.name.trim() || !cpForm.base_url.trim()) return;
    await addCustomProvider.mutateAsync({
      name: cpForm.name.trim(),
      base_url: cpForm.base_url.trim(),
      api_key: cpForm.api_key.trim() || undefined,
      default_model: cpForm.default_model.trim() || undefined,
    });
    setCpForm({ name: '', base_url: '', api_key: '', default_model: '' });
    setShowCustomForm(false);
  };

  // Auto-advance past auth if already authenticated
  useEffect(() => {
    if (!isAuthenticated || currentStep !== 1) return;
    if (configStatus === undefined) return; // still loading — wait
    if (!configStatus.needs_setup && !forceOpen) {
      // Already configured and not forced — go to dashboard
      router.push('/dashboard');
    } else {
      // Either needs setup OR opened manually with ?force=true — skip auth step
      setCurrentStep(2);
    }
  }, [isAuthenticated, configStatus, currentStep, router, forceOpen]);

  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token.trim()) return;

    setIsLoading(true);
    setError('');

    const success = await login(token);

    if (success) {
      setCurrentStep(2);
    } else {
      setError('Invalid token. Please verify and try again.');
    }

    setIsLoading(false);
  };

  const handleProviderComplete = () => {
    setCurrentStep(3);
  };

  const handleModelAndTelegramSave = async () => {
    if (!selectedModel) {
      toast.error('Please select a model');
      return;
    }

    try {
      await setModel.mutateAsync({ model: selectedModel, provider: selectedProvider });
      if (telegramToken.trim()) {
        await saveSetup.mutateAsync({ TELEGRAM_TOKEN: telegramToken.trim() });
      }
      setTelegramToken('');
      setCurrentStep(4); // → Google step
    } catch {
      toast.error('Failed to save settings');
    }
  };

  const handleGoogleSave = async () => {
    if (googleCredJson.trim()) {
      try {
        await saveGoogleCreds.mutateAsync(googleCredJson.trim());
        setGoogleCredJson('');
      } catch {
        return; // error handled by hook
      }
    }
    setCurrentStep(5);
  };

  // Progress: percentage through steps
  const progressPct = ((currentStep - 1) / (STEPS.length - 1)) * 100;

  return (
    <div
      className="min-h-screen flex"
      style={{ background: 'var(--acm-base)', position: 'relative' }}
    >
      {/* dot-grid overlay */}
      <div
        className="dot-grid"
        style={{
          position: 'fixed',
          inset: 0,
          opacity: 0.2,
          pointerEvents: 'none',
          zIndex: 0,
        }}
      />

      {/* Left panel */}
      <aside
        style={{
          width: 380,
          flexShrink: 0,
          background: 'linear-gradient(180deg, transparent, oklch(0.13 0.005 255))',
          borderRight: '1px solid var(--acm-border)',
          display: 'flex',
          flexDirection: 'column',
          padding: '40px 28px',
          gap: 32,
          position: 'sticky',
          top: 0,
          height: '100vh',
          zIndex: 1,
        }}
      >
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <ACMMark size={32} color="var(--acm-accent)" />
          <div>
            <div
              className="font-bold"
              style={{ fontSize: 18, color: 'var(--acm-fg)', letterSpacing: '-0.01em' }}
            >
              OpenACM
            </div>
            <div
              className="mono"
              style={{ fontSize: 10, color: 'var(--acm-fg-4)', letterSpacing: '0.12em', textTransform: 'uppercase' }}
            >
              SETUP · v2.3.1
            </div>
          </div>
        </div>

        {/* Progress bar */}
        <div>
          <div
            style={{
              height: 2,
              background: 'var(--acm-border)',
              borderRadius: 99,
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                height: '100%',
                width: `${progressPct}%`,
                background: 'var(--acm-accent)',
                borderRadius: 99,
                transition: 'width 400ms ease',
              }}
            />
          </div>
          <div
            className="mono"
            style={{ fontSize: 10, color: 'var(--acm-fg-4)', marginTop: 6, textAlign: 'right' }}
          >
            Step {currentStep} / {STEPS.length}
          </div>
        </div>

        {/* Steps */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
          {STEPS.map((step) => (
            <StepIndicator
              key={step.number}
              step={step}
              isActive={currentStep === step.number}
              isCompleted={currentStep > step.number}
            />
          ))}
        </div>

        {/* Footer trust signals */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 20,
            paddingTop: 16,
            borderTop: '1px solid var(--acm-border)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Shield size={13} style={{ color: 'var(--acm-ok)' }} />
            <span style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>Secure</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Zap size={13} style={{ color: 'var(--acm-accent)' }} />
            <span style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>Fast</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Lock size={13} style={{ color: 'var(--acm-fg-3)' }} />
            <span style={{ fontSize: 12, color: 'var(--acm-fg-4)' }}>Private</span>
          </div>
        </div>
      </aside>

      {/* Right panel */}
      <main
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '48px 40px',
          zIndex: 1,
          position: 'relative',
        }}
      >
        <div style={{ width: '100%', maxWidth: 560 }}>

          {/* ── Step 1: Auth ─────────────────────────────────────────────────── */}
          {currentStep === 1 && (
            <div
              style={{
                background: 'var(--acm-card)',
                border: '1px solid var(--acm-border)',
                borderRadius: 12,
                padding: '36px 32px',
              }}
            >
              <div style={{ marginBottom: 28 }}>
                <div className="label" style={{ marginBottom: 8 }}>Step 1</div>
                <h2
                  className="font-bold"
                  style={{ fontSize: 22, color: 'var(--acm-fg)', margin: 0, letterSpacing: '-0.02em' }}
                >
                  Welcome
                </h2>
                <p style={{ color: 'var(--acm-fg-3)', fontSize: 14, marginTop: 6 }}>
                  Enter your access token to start using OpenACM.
                </p>
              </div>

              <form onSubmit={handleAuth}>
                <div style={{ marginBottom: 24 }}>
                  <label
                    className="label"
                    style={{ display: 'block', marginBottom: 10 }}
                  >
                    Access Token
                  </label>
                  <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                    <Lock
                      size={14}
                      style={{
                        position: 'absolute',
                        left: 0,
                        color: 'var(--acm-fg-4)',
                        pointerEvents: 'none',
                      }}
                    />
                    <input
                      type="password"
                      value={token}
                      onChange={(e) => setToken(e.target.value)}
                      placeholder="Enter your token…"
                      className="acm-input mono"
                      style={{ paddingLeft: 22 }}
                      required
                    />
                  </div>
                  {error && (
                    <p
                      style={{
                        marginTop: 8,
                        fontSize: 12,
                        color: 'var(--acm-err)',
                      }}
                    >
                      {error}
                    </p>
                  )}
                </div>

                <button
                  type="submit"
                  disabled={isLoading || !token.trim()}
                  className="btn-primary"
                  style={{ width: '100%', justifyContent: 'center', padding: '10px 16px', fontSize: 14 }}
                >
                  {isLoading ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <>
                      <span>Continue</span>
                      <ArrowRight size={16} />
                    </>
                  )}
                </button>
              </form>

              <div
                style={{
                  marginTop: 20,
                  padding: '14px 16px',
                  background: 'var(--acm-elev)',
                  borderRadius: 8,
                  border: '1px solid var(--acm-border)',
                }}
              >
                <p style={{ fontSize: 12, color: 'var(--acm-fg-3)', margin: 0, lineHeight: 1.6 }}>
                  <span style={{ color: 'var(--acm-fg-2)', fontWeight: 600 }}>
                    Don&apos;t have a token?
                  </span>{' '}
                  The token is generated automatically when starting the OpenACM server. Check the
                  server console.
                </p>
              </div>
            </div>
          )}

          {/* ── Step 2: Providers ────────────────────────────────────────────── */}
          {currentStep === 2 && (
            <div
              style={{
                background: 'var(--acm-card)',
                border: '1px solid var(--acm-border)',
                borderRadius: 12,
                padding: '36px 32px',
              }}
            >
              <div style={{ marginBottom: 24 }}>
                <div className="label" style={{ marginBottom: 8 }}>Step 2</div>
                <h2
                  className="font-bold"
                  style={{ fontSize: 22, color: 'var(--acm-fg)', margin: 0, letterSpacing: '-0.02em' }}
                >
                  {t.steps.providers}
                </h2>
                <p style={{ color: 'var(--acm-fg-3)', fontSize: 14, marginTop: 6 }}>
                  {t.steps.providersDesc}
                </p>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                <ProviderSetupForm mode="onboarding" onComplete={handleProviderComplete} />

                {/* Custom provider section */}
                <div
                  style={{
                    borderTop: '1px solid var(--acm-border)',
                    paddingTop: 20,
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      marginBottom: 12,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Server size={13} style={{ color: 'var(--acm-fg-4)' }} />
                      <span
                        className="label"
                        style={{ color: 'var(--acm-fg-3)' }}
                      >
                        Custom / Self-hosted Provider
                      </span>
                    </div>
                    {!showCustomForm && (
                      <button
                        onClick={() => setShowCustomForm(true)}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 6,
                          padding: '5px 10px',
                          border: '1px dashed var(--acm-border-strong)',
                          borderRadius: 6,
                          background: 'transparent',
                          color: 'var(--acm-fg-4)',
                          fontSize: 12,
                          cursor: 'pointer',
                          transition: 'border-color 140ms, color 140ms',
                        }}
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--acm-accent)';
                          (e.currentTarget as HTMLButtonElement).style.color = 'var(--acm-accent)';
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--acm-border-strong)';
                          (e.currentTarget as HTMLButtonElement).style.color = 'var(--acm-fg-4)';
                        }}
                      >
                        <Plus size={11} /> Add
                      </button>
                    )}
                  </div>

                  {/* Existing custom providers */}
                  {customProviders.length > 0 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
                      {customProviders.map(cp => (
                        <div
                          key={cp.id}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 8,
                            padding: '8px 12px',
                            background: 'var(--acm-elev)',
                            borderRadius: 6,
                            border: '1px solid var(--acm-border)',
                          }}
                        >
                          <CheckCircle size={12} style={{ color: 'var(--acm-ok)', flexShrink: 0 }} />
                          <span style={{ fontSize: 13, color: 'var(--acm-fg)', fontWeight: 500 }}>
                            {cp.name}
                          </span>
                          <span
                            className="mono"
                            style={{ fontSize: 11, color: 'var(--acm-fg-4)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                          >
                            {cp.base_url}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  {showCustomForm && (
                    <div
                      style={{
                        padding: '16px',
                        borderRadius: 8,
                        border: '1px solid oklch(0.84 0.16 82 / 0.18)',
                        background: 'var(--acm-accent-soft)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 12,
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <span className="label" style={{ color: 'var(--acm-fg-2)' }}>
                          New Custom Provider
                        </span>
                        <button
                          onClick={() => setShowCustomForm(false)}
                          style={{
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            color: 'var(--acm-fg-4)',
                            padding: 2,
                          }}
                        >
                          <X size={13} />
                        </button>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                        <div>
                          <label className="label" style={{ display: 'block', marginBottom: 8 }}>
                            Name <span style={{ color: 'var(--acm-err)' }}>*</span>
                          </label>
                          <input
                            value={cpForm.name}
                            onChange={e => setCpForm(p => ({ ...p, name: e.target.value }))}
                            placeholder="e.g. LM Studio"
                            className="acm-input"
                          />
                        </div>
                        <div>
                          <label className="label" style={{ display: 'block', marginBottom: 8 }}>
                            Base URL <span style={{ color: 'var(--acm-err)' }}>*</span>
                          </label>
                          <input
                            value={cpForm.base_url}
                            onChange={e => setCpForm(p => ({ ...p, base_url: e.target.value }))}
                            placeholder="http://localhost:1234/v1"
                            className="acm-input mono"
                          />
                        </div>
                        <div>
                          <label className="label" style={{ display: 'block', marginBottom: 8 }}>
                            Default Model
                          </label>
                          <input
                            value={cpForm.default_model}
                            onChange={e => setCpForm(p => ({ ...p, default_model: e.target.value }))}
                            placeholder="llama-3.1-8b"
                            className="acm-input mono"
                          />
                        </div>
                        <div>
                          <label className="label" style={{ display: 'block', marginBottom: 8 }}>
                            API Key (optional)
                          </label>
                          <input
                            type="password"
                            value={cpForm.api_key}
                            onChange={e => setCpForm(p => ({ ...p, api_key: e.target.value }))}
                            placeholder="sk-… or leave blank"
                            className="acm-input mono"
                          />
                        </div>
                      </div>
                      <button
                        onClick={handleAddCustomProvider}
                        disabled={!cpForm.name.trim() || !cpForm.base_url.trim() || addCustomProvider.isPending}
                        className="btn-primary"
                        style={{ alignSelf: 'flex-start' }}
                      >
                        {addCustomProvider.isPending ? (
                          <Loader2 size={13} className="animate-spin" />
                        ) : (
                          <Plus size={13} />
                        )}
                        Add Provider
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ── Step 3: Model & Telegram ─────────────────────────────────────── */}
          {currentStep === 3 && (
            <div
              style={{
                background: 'var(--acm-card)',
                border: '1px solid var(--acm-border)',
                borderRadius: 12,
                padding: '36px 32px',
              }}
            >
              <div style={{ marginBottom: 24 }}>
                <div className="label" style={{ marginBottom: 8 }}>Step 3</div>
                <h2
                  className="font-bold"
                  style={{ fontSize: 22, color: 'var(--acm-fg)', margin: 0, letterSpacing: '-0.02em' }}
                >
                  {t.steps.modelTelegram}
                </h2>
                <p style={{ color: 'var(--acm-fg-3)', fontSize: 14, marginTop: 6 }}>
                  {t.steps.modelTelegramDesc}
                </p>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
                <ModelSelector
                  selectedModel={selectedModel}
                  onSelect={({ model, provider }) => {
                    setSelectedModel(model);
                    setSelectedProvider(provider);
                  }}
                />

                <div
                  style={{
                    borderTop: '1px solid var(--acm-border)',
                    paddingTop: 24,
                  }}
                >
                  <TelegramSetup value={telegramToken} onChange={setTelegramToken} />
                </div>

                <div style={{ display: 'flex', gap: 10, paddingTop: 4 }}>
                  <button
                    onClick={() => setCurrentStep(2)}
                    className="btn-secondary"
                  >
                    <ArrowLeft size={15} />
                    Back
                  </button>
                  <button
                    onClick={handleModelAndTelegramSave}
                    disabled={!selectedModel || setModel.isPending || saveSetup.isPending}
                    className="btn-primary"
                    style={{ flex: 1, justifyContent: 'center', padding: '10px 16px', fontSize: 14 }}
                  >
                    {setModel.isPending || saveSetup.isPending ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <>
                        <span>Save &amp; Continue</span>
                        <ArrowRight size={16} />
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* ── Step 4: Google Services ──────────────────────────────────────── */}
          {currentStep === 4 && (
            <div
              style={{
                background: 'var(--acm-card)',
                border: '1px solid var(--acm-border)',
                borderRadius: 12,
                padding: '36px 32px',
              }}
            >
              <div style={{ marginBottom: 24 }}>
                <div className="label" style={{ marginBottom: 8 }}>Step 4 — Optional</div>
                <h2
                  className="font-bold"
                  style={{ fontSize: 22, color: 'var(--acm-fg)', margin: 0, letterSpacing: '-0.02em' }}
                >
                  Google Services
                </h2>
                <p style={{ color: 'var(--acm-fg-3)', fontSize: 14, marginTop: 6 }}>
                  Lets the AI use Gmail, Calendar, Drive and YouTube. You can skip and configure later.
                </p>
              </div>

              {/* Status badges */}
              <div style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '8px 12px',
                    borderRadius: 8,
                    border: `1px solid ${googleStatus?.credentials_exist ? 'oklch(0.75 0.09 160 / 0.3)' : 'var(--acm-border)'}`,
                    background: googleStatus?.credentials_exist ? 'oklch(0.75 0.09 160 / 0.08)' : 'var(--acm-elev)',
                    flex: 1,
                    fontSize: 13,
                    color: googleStatus?.credentials_exist ? 'var(--acm-ok)' : 'var(--acm-fg-4)',
                  }}
                >
                  <CheckCircle size={13} style={{ opacity: googleStatus?.credentials_exist ? 1 : 0.3 }} />
                  Credentials
                </div>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '8px 12px',
                    borderRadius: 8,
                    border: `1px solid ${googleStatus?.token_exist ? 'oklch(0.75 0.09 160 / 0.3)' : 'var(--acm-border)'}`,
                    background: googleStatus?.token_exist ? 'oklch(0.75 0.09 160 / 0.08)' : 'var(--acm-elev)',
                    flex: 1,
                    fontSize: 13,
                    color: googleStatus?.token_exist ? 'var(--acm-ok)' : 'var(--acm-fg-4)',
                  }}
                >
                  <CheckCircle size={13} style={{ opacity: googleStatus?.token_exist ? 1 : 0.3 }} />
                  Authorized
                </div>
              </div>

              {/* If already fully connected */}
              {googleStatus?.token_exist ? (
                <div
                  style={{
                    padding: '20px',
                    background: 'oklch(0.75 0.09 160 / 0.08)',
                    border: '1px solid oklch(0.75 0.09 160 / 0.25)',
                    borderRadius: 10,
                    textAlign: 'center',
                    marginBottom: 20,
                  }}
                >
                  <CheckCircle size={22} style={{ color: 'var(--acm-ok)', margin: '0 auto 8px' }} />
                  <p style={{ color: 'var(--acm-ok)', fontWeight: 600, margin: 0 }}>Google is connected!</p>
                  <p style={{ color: 'var(--acm-fg-3)', fontSize: 13, marginTop: 4 }}>
                    Gmail, Calendar, Drive and YouTube are ready.
                  </p>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginBottom: 20 }}>
                  {/* Step 1: credentials */}
                  {!googleStatus?.credentials_exist && (
                    <>
                      <div
                        style={{
                          padding: '12px 14px',
                          background: 'var(--acm-elev)',
                          borderRadius: 8,
                          border: '1px solid var(--acm-border)',
                        }}
                      >
                        <p
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 6,
                            fontSize: 12,
                            fontWeight: 600,
                            color: 'var(--acm-fg-2)',
                            margin: '0 0 8px',
                          }}
                        >
                          <Globe2 size={13} style={{ color: 'var(--acm-fg-3)' }} /> How to get credentials:
                        </p>
                        <ol
                          style={{
                            margin: 0,
                            paddingLeft: 18,
                            fontSize: 12,
                            color: 'var(--acm-fg-3)',
                            lineHeight: 1.7,
                          }}
                        >
                          <li>Google Cloud Console → APIs &amp; Services → Credentials</li>
                          <li>Create OAuth 2.0 credentials (Desktop application)</li>
                          <li>Enable: Gmail, Calendar, Drive, YouTube APIs</li>
                          <li>Download JSON and paste below</li>
                        </ol>
                      </div>
                      <textarea
                        value={googleCredJson}
                        onChange={(e) => setGoogleCredJson(e.target.value)}
                        placeholder={'{\n  "installed": { "client_id": "...", ... }\n}'}
                        rows={4}
                        className="mono"
                        style={{
                          width: '100%',
                          padding: '10px 12px',
                          background: 'var(--acm-elev)',
                          border: '1px solid var(--acm-border)',
                          borderRadius: 8,
                          color: 'var(--acm-fg)',
                          fontSize: 12,
                          outline: 'none',
                          resize: 'none',
                          boxSizing: 'border-box',
                          transition: 'border-color 160ms',
                        }}
                        onFocus={(e) => { e.currentTarget.style.borderColor = 'var(--acm-accent)'; }}
                        onBlur={(e) => { e.currentTarget.style.borderColor = 'var(--acm-border)'; }}
                        spellCheck={false}
                      />
                      <button
                        onClick={handleGoogleSave}
                        disabled={!googleCredJson.trim() || saveGoogleCreds.isPending}
                        className="btn-primary"
                        style={{ width: '100%', justifyContent: 'center', padding: '10px 16px', fontSize: 14 }}
                      >
                        {saveGoogleCreds.isPending ? (
                          <Loader2 size={16} className="animate-spin" />
                        ) : (
                          <><CheckCircle size={16} /><span>Save Credentials</span></>
                        )}
                      </button>
                    </>
                  )}

                  {/* Step 2: authorize */}
                  {googleStatus?.credentials_exist && !googleStatus?.token_exist && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                      <div
                        style={{
                          padding: '12px 14px',
                          background: 'var(--acm-accent-soft)',
                          border: '1px solid oklch(0.84 0.16 82 / 0.18)',
                          borderRadius: 8,
                          fontSize: 13,
                          color: 'var(--acm-fg-2)',
                        }}
                      >
                        <p style={{ fontWeight: 600, margin: '0 0 4px', color: 'var(--acm-accent)' }}>
                          Credentials uploaded ✓
                        </p>
                        <p style={{ margin: 0, color: 'var(--acm-fg-3)' }}>
                          Now authorize OpenACM to access your Google account. A new tab will open — sign in and click Allow.
                        </p>
                      </div>
                      <button
                        onClick={() => startGoogleAuth.mutate()}
                        disabled={startGoogleAuth.isPending}
                        className="btn-primary"
                        style={{ width: '100%', justifyContent: 'center', padding: '10px 16px', fontSize: 14 }}
                      >
                        {startGoogleAuth.isPending ? (
                          <Loader2 size={16} className="animate-spin" />
                        ) : (
                          <><Globe2 size={16} /><span>Connect with Google</span></>
                        )}
                      </button>
                      {startGoogleAuth.isSuccess && (
                        <p
                          style={{
                            textAlign: 'center',
                            fontSize: 12,
                            color: 'var(--acm-fg-3)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: 8,
                          }}
                        >
                          <Loader2 size={13} className="animate-spin" />
                          Waiting for authorization in the browser tab…
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )}

              <div style={{ display: 'flex', gap: 10 }}>
                <button
                  onClick={() => setCurrentStep(3)}
                  className="btn-secondary"
                >
                  <ArrowLeft size={15} /> Back
                </button>
                <button
                  onClick={() => setCurrentStep(5)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '7px 13px',
                    background: 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                    color: 'var(--acm-fg-4)',
                    fontSize: 13,
                  }}
                >
                  <ChevronsRight size={15} /> Skip for now
                </button>
                {googleStatus?.token_exist && (
                  <button
                    onClick={() => setCurrentStep(5)}
                    className="btn-primary"
                    style={{ flex: 1, justifyContent: 'center', padding: '10px 16px', fontSize: 14 }}
                  >
                    <span>Continue</span><ArrowRight size={16} />
                  </button>
                )}
              </div>
            </div>
          )}

          {/* ── Step 5: Ready ────────────────────────────────────────────────── */}
          {currentStep === 5 && (
            <div
              style={{
                background: 'var(--acm-card)',
                border: '1px solid var(--acm-border)',
                borderRadius: 12,
                padding: '56px 32px',
                textAlign: 'center',
              }}
            >
              {/* Icon */}
              <div
                style={{
                  width: 72,
                  height: 72,
                  borderRadius: '50%',
                  background: 'var(--acm-accent-soft)',
                  border: '1px solid oklch(0.84 0.16 82 / 0.2)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  margin: '0 auto 24px',
                }}
              >
                <Rocket size={32} style={{ color: 'var(--acm-accent)' }} />
              </div>

              <h2
                className="font-bold"
                style={{
                  fontSize: 26,
                  color: 'var(--acm-fg)',
                  margin: '0 0 10px',
                  letterSpacing: '-0.02em',
                }}
              >
                {t.readyScreen.title}
              </h2>
              <p
                style={{
                  color: 'var(--acm-fg-3)',
                  fontSize: 14,
                  margin: '0 auto 32px',
                  maxWidth: 360,
                  lineHeight: 1.6,
                }}
              >
                {t.readyScreen.subtitle}
              </p>

              <button
                onClick={() => router.push('/dashboard')}
                className="btn-primary"
                style={{ fontSize: 14, padding: '11px 28px' }}
              >
                {t.readyScreen.goToDashboard}
                <ArrowRight size={16} />
              </button>

              {/* Decorative footer */}
              <div
                style={{
                  marginTop: 40,
                  paddingTop: 24,
                  borderTop: '1px solid var(--acm-border)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 8,
                }}
              >
                <ACMMark size={16} color="var(--acm-fg-4)" />
                <span className="mono" style={{ fontSize: 11, color: 'var(--acm-fg-4)' }}>
                  OpenACM · ready
                </span>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

export default function OnboardingPage() {
  return (
    <Suspense
      fallback={
        <div
          style={{
            minHeight: '100vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'var(--acm-base)',
          }}
        >
          <Loader2
            size={28}
            className="animate-spin"
            style={{ color: 'var(--acm-accent)' }}
          />
        </div>
      }
    >
      <OnboardingContent />
    </Suspense>
  );
}
