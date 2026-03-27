'use client'

import { useEffect } from 'react'
import { AlertTriangle } from 'lucide-react'

interface ErrorProps {
  error: Error & { digest?: string }
  reset: () => void
}

export default function Error({ error, reset }: ErrorProps) {
  useEffect(() => {
    console.error('ErrorBoundary caught an error:', error)
  }, [error])

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 p-4">
      <div className="max-w-md w-full bg-slate-900 rounded-xl border border-slate-800 p-8 text-center">
        <div className="flex justify-center mb-4">
          <div className="p-3 bg-red-500/20 rounded-full">
            <AlertTriangle className="w-8 h-8 text-red-500" />
          </div>
        </div>

        <h2 className="text-xl font-bold text-white mb-2">
          Something went wrong
        </h2>

        <p className="text-slate-400 mb-6">
          An unexpected error occurred. Try reloading the page.
        </p>

        {error.message && (
          <div className="mb-6 p-3 bg-slate-800 rounded-lg text-left">
            <p className="text-xs text-slate-500 mb-1">Error:</p>
            <p className="text-sm text-red-400 font-mono break-all">
              {error.message}
            </p>
          </div>
        )}

        <div className="flex gap-3 justify-center">
          <button
            onClick={reset}
            className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors"
          >
            Try again
          </button>

          <button
            onClick={() => window.location.reload()}
            className="px-6 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 font-medium rounded-lg transition-colors"
          >
            Reload page
          </button>
        </div>
      </div>
    </div>
  )
}
