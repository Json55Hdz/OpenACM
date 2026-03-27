'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/hooks/use-websocket';
import { 
  Brain, 
  ArrowRight, 
  CheckCircle, 
  Shield, 
  Zap,
  Lock,
  Loader2
} from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

function Step({ 
  number, 
  title, 
  description, 
  isActive, 
  isCompleted 
}: { 
  number: number;
  title: string;
  description: string;
  isActive: boolean;
  isCompleted: boolean;
}) {
  return (
    <div className={cn(
      "flex items-start gap-4 p-4 rounded-xl transition-all",
      isActive ? "bg-blue-600/10 border border-blue-600/30" : "bg-slate-800/50"
    )}>
      <div className={cn(
        "w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 font-semibold text-sm",
        isCompleted ? "bg-green-500 text-white" :
        isActive ? "bg-blue-600 text-white" : "bg-slate-700 text-slate-400"
      )}>
        {isCompleted ? <CheckCircle size={16} /> : number}
      </div>
      <div>
        <h3 className={cn(
          "font-medium",
          isActive ? "text-white" : "text-slate-400"
        )}>
          {title}
        </h3>
        <p className="text-sm text-slate-500 mt-1">{description}</p>
      </div>
    </div>
  );
}

export default function OnboardingPage() {
  const router = useRouter();
  const { login, isAuthenticated } = useAuth();
  const [currentStep, setCurrentStep] = useState(1);
  const [token, setToken] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  
  // Redirect if already authenticated
  if (isAuthenticated) {
    router.push('/dashboard');
    return null;
  }
  
  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token.trim()) return;
    
    setIsLoading(true);
    setError('');
    
    const success = await login(token);
    
    if (success) {
      setCurrentStep(2);
      setTimeout(() => {
        router.push('/dashboard');
      }, 1000);
    } else {
      setError('Invalid token. Please verify and try again.');
    }
    
    setIsLoading(false);
  };
  
  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
      <div className="w-full max-w-4xl grid lg:grid-cols-2 gap-8 items-center">
        {/* Left Side - Info */}
        <div className="space-y-8">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 bg-blue-600 rounded-xl flex items-center justify-center">
              <Brain size={28} className="text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">OpenACM</h1>
              <p className="text-slate-400">AI Assistant Console</p>
            </div>
          </div>
          
          <div className="space-y-4">
            <Step
              number={1}
              title="Authentication"
              description="Enter your access token to connect to the system."
              isActive={currentStep === 1}
              isCompleted={currentStep > 1}
            />
            <Step
              number={2}
              title="Initial Setup"
              description="Review the model and channel configuration."
              isActive={currentStep === 2}
              isCompleted={currentStep > 2}
            />
            <Step
              number={3}
              title="Ready!"
              description="Start interacting with your AI assistant."
              isActive={currentStep === 3}
              isCompleted={currentStep > 3}
            />
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
        
        {/* Right Side - Auth Form */}
        <div className="bg-slate-900 rounded-2xl border border-slate-800 p-8">
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
                    <Lock className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" size={20} />
                    <input
                      type="password"
                      value={token}
                      onChange={(e) => setToken(e.target.value)}
                      placeholder="Enter your token..."
                      className="w-full pl-12 pr-4 py-3 bg-slate-800 border border-slate-700 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
                      required
                    />
                  </div>
                  {error && (
                    <p className="mt-2 text-sm text-red-400">{error}</p>
                  )}
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
                  <strong className="text-slate-300">Don't have a token?</strong>
                  <br />
                  The token is generated automatically when starting the OpenACM server.
                  Check the server console.
                </p>
              </div>
            </>
          )}
          
          {currentStep === 2 && (
            <div className="text-center py-8">
              <div className="w-16 h-16 bg-green-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
                <CheckCircle size={32} className="text-green-400" />
              </div>
              <h2 className="text-xl font-bold text-white mb-2">Authentication Successful!</h2>
              <p className="text-slate-400">Redirecting to dashboard...</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
