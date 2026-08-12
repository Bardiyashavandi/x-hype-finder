import { type FormEvent, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { useAuthStatus, useLogin } from '../hooks/useAuth'

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const navigate = useNavigate()
  const location = useLocation()
  const { data: authStatus } = useAuthStatus()
  const login = useLogin()

  // Already logged in (e.g. navigated back to /login manually) — bounce to
  // wherever the guard originally sent them, or the default landing page.
  if (authStatus?.authenticated) {
    const from = (location.state as { from?: string } | null)?.from ?? '/topics'
    return <Navigate to={from} replace />
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    login.mutate(
      { email, password },
      { onSuccess: () => navigate('/topics', { replace: true }) },
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-lg border border-surface-border bg-surface-raised p-8"
      >
        <h1 className="mb-1 text-lg font-semibold text-gray-100">X Hype Finder</h1>
        <p className="mb-6 text-sm text-gray-400">Sign in to your account.</p>

        <label htmlFor="email" className="mb-1 block text-sm text-gray-300">
          Email
        </label>
        <input
          id="email"
          type="email"
          autoFocus
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="mb-4 w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-gray-100 outline-none focus:border-pipeline"
        />

        <label htmlFor="password" className="mb-1 block text-sm text-gray-300">
          Password
        </label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mb-4 w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-gray-100 outline-none focus:border-pipeline"
        />

        {login.isError && (
          <p className="mb-4 text-sm text-status-error">
            {login.error instanceof Error ? login.error.message : 'Login failed.'}
          </p>
        )}

        <button
          type="submit"
          disabled={login.isPending || email.length === 0 || password.length === 0}
          className="w-full rounded-md bg-pipeline px-3 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {login.isPending ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
