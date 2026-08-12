import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { useAuthStatus } from './hooks/useAuth'
import { DashboardLayout } from './layout/DashboardLayout'
import { DigestDetailPage } from './pages/DigestDetailPage'
import { DigestsPage } from './pages/DigestsPage'
import { DraftsPage } from './pages/DraftsPage'
import { EvalPage } from './pages/EvalPage'
import { IdeaValidationPage } from './pages/IdeaValidationPage'
import { LoginPage } from './pages/LoginPage'
import { TopicsPage } from './pages/TopicsPage'

/** Gates every dashboard route behind `GET /api/auth/me` (src/web/routers/auth.py)
 * — unauthenticated visitors are redirected to /login (carrying the page
 * they wanted, so LoginPage can send them back after signing in); nothing
 * dashboard-shaped renders until the check resolves, so an authenticated
 * page's data-fetching hooks (step 3) never fire a request the backend
 * would 401 anyway. */
function AuthGuard({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { data, isPending, isError } = useAuthStatus()

  if (isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-gray-400">
        Loading…
      </div>
    )
  }

  if (isError || !data?.authenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <>{children}</>
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route
        element={
          <AuthGuard>
            <DashboardLayout />
          </AuthGuard>
        }
      >
        <Route index element={<Navigate to="/topics" replace />} />
        <Route path="/topics" element={<TopicsPage />} />
        <Route path="/digests" element={<DigestsPage />} />
        <Route path="/digests/:id" element={<DigestDetailPage />} />
        <Route path="/drafts" element={<DraftsPage />} />
        <Route path="/idea-validation" element={<IdeaValidationPage />} />
        <Route path="/eval" element={<EvalPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/topics" replace />} />
    </Routes>
  )
}
