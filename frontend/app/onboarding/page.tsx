'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/hooks/use-websocket';
import { useConfigStatus, useSaveSetup, useSetModel, useGoogleStatus, useSaveGoogleCredentials, useStartGoogleAuth } from '@/hooks/use-setup';
import { ProviderSetupForm } from '@/components/setup/provider-setup-form';
import { ModelSelector } from '@/components/setup/model-selector';
import { TelegramSetup } from '@/components/setup/telegram-setup';
import { translations } from '@/lib/translations';
import {
  Brain,
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
      className={cn(
        'flex items-start gap-4 p-4 rounded-xl transition-all',
        isActive ? 'bg-blue-600/10 border border-blue-600/30' : 'bg-slate-800/50'
      )}
    >
      <div
        className={cn(
          'w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 font-semibold text-sm',
          isCompleted
            ? 'bg-green-500 text-white'
            : isActive
              ? 'bg-blue-600 text-white'
              : 'bg-slate-700 text-slate-400'
        )}
      >
        {isCompleted ? <CheckCircle size={16} /> : step.number}
      </div>
      <div>
        <h3 className={cn('font-medium', isActive ? 'text-white' : 'text-slate-400')}>
          {step.title}
        </h3>
        <p className="text-sm text-slate-500 mt-1">{step.description}</p>
      </div>
    </div>
  );
}

export default function OnboardingPage() {
  const router = useRouter();
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

  // Auto-advance past auth if already authenticated
  useEffect(() => {
    if (!isAuthenticated || currentStep !== 1) return;
    if (configStatus === undefined) return; // still loading — wait
    if (!configStatus.needs_setup) {
      router.push('/dashboard');
    } else {
      setCurrentStep(2);
    }
  }, [isAuthenticated, configStatus, currentStep, router]);

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

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
      <div className="w-full max-w-5xl grid lg:grid-cols-[320px_1fr] gap-8 items-start">
        {/* Left Side - Steps */}
        <div className="space-y-8 lg:sticky lg:top-8">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 bg-blue-600 rounded-xl flex items-center justify-center">
              <Brain size={28} className="text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">OpenACM</h1>
              <p className="text-slate-400">AI Assistant Console</p>
            </div>
          </div>

          <div className="space-y-3">
            {STEPS.map((step) => (
              <StepIndicator
                key={step.number}
                step={step}
                isActive={currentStep === step.number}
                isCompleted={currentStep > step.number}
              />
            ))}
          </div>

          <div className="flex items-center gap-6 text-sm text-slate-500">
            <div className="flex items-center gap-2">
              <Shield size={16} className="text-green-400" />
              <span>Secure</span>
            </div>
            <div className="flex items-center gap-2">
              <Zap size={16} className="text-yellow-400" />
              <span>Fast</span>
            </div>
            <div className="flex items-center gap-2">
              <Lock size={16} className="text-blue-400" />
              <span>Private</span>
            </div>
          </div>
        </div>

        {/* Right Side - Content */}
        <div className="bg-slate-900 rounded-2xl border border-slate-800 p-8">
          {/* Step 1: Auth */}
          {currentStep === 1 && (
            <>
              <h2 className="text-2xl font-bold text-white mb-2">Welcome</h2>
              <p className="text-slate-400 mb-8">
                Enter your access token to start using OpenACM.
              </p>

              <form onSubmit={handleAuth} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-2">
                    Access Token
                  </label>
                  <div className="relative">
                    <Lock
                      className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500"
                      size={20}
                    />
                    <input
                      type="password"
                      value={token}
                      onChange={(e) => setToken(e.target.value)}
                      placeholder="Enter your token..."
                      className="w-full pl-12 pr-4 py-3 bg-slate-800 border border-slate-700 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
                      required
                    />
                  </div>
                  {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
                </div>

                <button
                  type="submit"
                  disabled={isLoading || !token.trim()}
                  className="w-full flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl font-medium transition-colors"
                >
                  {isLoading ? (
                    <Loader2 size={20} className="animate-spin" />
                  ) : (
                    <>
                      <span>Continue</span>
                      <ArrowRight size={20} />
                    </>
                  )}
                </button>
              </form>

              <div className="mt-6 p-4 bg-slate-800/50 rounded-lg">
                <p className="text-sm text-slate-400">
                  <strong className="text-slate-300">Don&apos;t have a token?</strong>
                  <br />
                  The token is generated automatically when starting the OpenACM server. Check
                  the server console.
                </p>
              </div>
            </>
          )}

          {/* Step 2: Providers */}
          {currentStep === 2 && (
            <ProviderSetupForm mode="onboarding" onComplete={handleProviderComplete} />
          )}

          {/* Step 3: Model & Telegram */}
          {currentStep === 3 && (
            <div className="space-y-8">
              <ModelSelector
                selectedModel={selectedModel}
                onSelect={({ model, provider }) => {
                  setSelectedModel(model);
                  setSelectedProvider(provider);
                }}
              />

              <div className="border-t border-slate-700 pt-6">
                <TelegramSetup value={telegramToken} onChange={setTelegramToken} />
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => setCurrentStep(2)}
                  className="flex items-center gap-2 px-4 py-3 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl font-medium transition-colors"
                >
                  <ArrowLeft size={18} />
                  Back
                </button>
                <button
                  onClick={handleModelAndTelegramSave}
                  disabled={!selectedModel || setModel.isPending || saveSetup.isPending}
                  className="flex-1 flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl font-medium transition-colors"
                >
                  {setModel.isPending || saveSetup.isPending ? (
                    <Loader2 size={18} className="animate-spin" />
                  ) : (
                    <>
                      <span>Save & Continue</span>
                      <ArrowRight size={18} />
                    </>
                  )}
                </button>
              </div>
            </div>
          )}

          {/* Step 4: Google Services (optional) */}
          {currentStep === 4 && (
            <div className="space-y-6">
              <div>
                <h2 className="text-xl font-bold text-white mb-1">Google Services</h2>
                <p className="text-sm text-slate-400">
                  Optional — lets the AI use Gmail, Calendar, Drive and YouTube. You can skip and configure later.
                </p>
              </div>

              {/* Status badges */}
              <div className="flex gap-3">
                <div className={cn(
                  "flex items-center gap-2 px-3 py-2 rounded-lg border text-sm flex-1",
                  googleStatus?.credentials_exist
                    ? "bg-green-500/10 border-green-500/30 text-green-400"
                    : "bg-slate-800 border-slate-700 text-slate-500"
                )}>
                  <CheckCircle size={14} className={googleStatus?.credentials_exist ? '' : 'opacity-30'} />
                  Credentials
                </div>
                <div className={cn(
                  "flex items-center gap-2 px-3 py-2 rounded-lg border text-sm flex-1",
                  googleStatus?.token_exist
                    ? "bg-green-500/10 border-green-500/30 text-green-400"
                    : "bg-slate-800 border-slate-700 text-slate-500"
                )}>
                  <CheckCircle size={14} className={googleStatus?.token_exist ? '' : 'opacity-30'} />
                  Authorized
                </div>
              </div>

              {/* If already fully connected */}
              {googleStatus?.token_exist ? (
                <div className="p-4 bg-green-500/10 border border-green-500/30 rounded-xl text-center">
                  <CheckCircle size={24} className="text-green-400 mx-auto mb-2" />
                  <p className="text-green-400 font-medium">Google is connected!</p>
                  <p className="text-slate-400 text-sm mt-1">Gmail, Calendar, Drive and YouTube are ready.</p>
                </div>
              ) : (
                <>
                  {/* Step 1: credentials */}
                  {!googleStatus?.credentials_exist && (
                    <>
                      <div className="p-3 bg-slate-800/50 rounded-lg text-xs text-slate-400 space-y-1">
                        <p className="font-medium text-slate-300 flex items-center gap-1.5">
                          <Globe2 size={14} /> How to get credentials:
                        </p>
                        <ol className="list-decimal list-inside space-y-0.5">
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
                        className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-slate-300 font-mono text-xs focus:outline-none focus:border-blue-500 resize-none"
                        spellCheck={false}
                      />
                      <button
                        onClick={handleGoogleSave}
                        disabled={!googleCredJson.trim() || saveGoogleCreds.isPending}
                        className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-xl font-medium transition-colors"
                      >
                        {saveGoogleCreds.isPending ? <Loader2 size={18} className="animate-spin" /> : <><CheckCircle size={18} /><span>Save Credentials</span></>}
                      </button>
                    </>
                  )}

                  {/* Step 2: authorize */}
                  {googleStatus?.credentials_exist && !googleStatus?.token_exist && (
                    <div className="space-y-3">
                      <div className="p-3 bg-blue-500/10 border border-blue-500/30 rounded-lg text-sm text-blue-300">
                        <p className="font-medium mb-1">Credentials uploaded ✓</p>
                        <p className="text-blue-400/80">Now authorize OpenACM to access your Google account. A new tab will open — sign in and click Allow.</p>
                      </div>
                      <button
                        onClick={() => startGoogleAuth.mutate()}
                        disabled={startGoogleAuth.isPending}
                        className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 disabled:opacity-50 text-white rounded-xl font-medium transition-colors"
                      >
                        {startGoogleAuth.isPending ? (
                          <Loader2 size={18} className="animate-spin" />
                        ) : (
                          <><Globe2 size={18} /><span>Connect with Google</span></>
                        )}
                      </button>
                      {startGoogleAuth.isSuccess && (
                        <p className="text-center text-sm text-slate-400 flex items-center justify-center gap-2">
                          <Loader2 size={14} className="animate-spin" /> Waiting for authorization in the browser tab...
                        </p>
                      )}
                    </div>
                  )}
                </>
              )}

              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => setCurrentStep(3)}
                  className="flex items-center gap-2 px-4 py-3 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl font-medium transition-colors"
                >
                  <ArrowLeft size={18} /> Back
                </button>
                <button
                  onClick={() => setCurrentStep(5)}
                  className="flex items-center gap-2 px-4 py-3 bg-slate-800 hover:bg-slate-700 text-slate-400 rounded-xl font-medium transition-colors"
                >
                  <ChevronsRight size={18} /> Skip
                </button>
                {googleStatus?.token_exist && (
                  <button
                    onClick={() => setCurrentStep(5)}
                    className="flex-1 flex items-center justify-center gap-2 px-6 py-3 bg-green-600 hover:bg-green-700 text-white rounded-xl font-medium transition-colors"
                  >
                    <span>Continue</span><ArrowRight size={18} />
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Step 5: Ready */}
          {currentStep === 5 && (
            <div className="text-center py-12">
              <div className="w-20 h-20 bg-green-500/20 rounded-full flex items-center justify-center mx-auto mb-6">
                <Rocket size={40} className="text-green-400" />
              </div>
              <h2 className="text-2xl font-bold text-white mb-3">
                {t.readyScreen.title}
              </h2>
              <p className="text-slate-400 mb-8 max-w-sm mx-auto">
                {t.readyScreen.subtitle}
              </p>
              <button
                onClick={() => router.push('/dashboard')}
                className="inline-flex items-center gap-2 px-8 py-3 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white font-medium rounded-xl transition-all"
              >
                {t.readyScreen.goToDashboard}
                <ArrowRight size={18} />
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
