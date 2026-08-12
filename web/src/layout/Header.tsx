import { useNavigate } from 'react-router-dom'

import { useAuthStatus, useLogout } from '../hooks/useAuth'

export function Header() {
  const navigate = useNavigate()
  const logout = useLogout()
  const { data: authStatus } = useAuthStatus()

  const handleLogout = () => {
    logout.mutate(undefined, {
      onSuccess: () => navigate('/login', { replace: true }),
    })
  }

  return (
    <header className="flex items-center justify-between border-b border-surface-border bg-surface-raised px-6 py-3">
      <div className="text-sm text-gray-400">
        {authStatus?.email ? `Logged in as ${authStatus.email}` : 'Dashboard'}
      </div>
      <button
        type="button"
        onClick={handleLogout}
        disabled={logout.isPending}
        className="rounded-md border border-surface-border px-3 py-1.5 text-sm text-gray-300 transition-colors hover:bg-surface hover:text-gray-100 disabled:opacity-50"
      >
        {logout.isPending ? 'Logging out…' : 'Log out'}
      </button>
    </header>
  )
}
