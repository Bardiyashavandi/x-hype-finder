// Wraps the three /api/auth/* endpoints (src/web/routers/auth.py) for the
// frontend's boot check and login/logout flows (specs/003-web-dashboard/plan.md
// §2). `App.tsx`'s auth guard reads `useAuthStatus()` to decide whether a
// route renders or redirects to /login.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'

export interface AuthStatus {
  authenticated: boolean
}

export const AUTH_QUERY_KEY = ['auth', 'me'] as const

export function useAuthStatus() {
  return useQuery({
    queryKey: AUTH_QUERY_KEY,
    queryFn: () => api.get<AuthStatus>('/api/auth/me'),
    // The guard needs the *current* answer the moment a route mounts, not a
    // stale cached one — this check is cheap and rare enough that always
    // refetching is simpler than reasoning about staleness here.
    staleTime: 0,
  })
}

export function useLogin() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (password: string) => api.post<AuthStatus>('/api/auth/login', { password }),
    onSuccess: (data) => queryClient.setQueryData(AUTH_QUERY_KEY, data),
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<AuthStatus>('/api/auth/logout'),
    onSuccess: (data) => queryClient.setQueryData(AUTH_QUERY_KEY, data),
  })
}
