import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { Draft, DraftStatus } from '../api/types'

export const DRAFTS_QUERY_KEY = ['drafts'] as const

export function useDrafts(status: DraftStatus | 'all') {
  return useQuery({
    queryKey: [...DRAFTS_QUERY_KEY, status],
    queryFn: () => {
      const path = status === 'all' ? '/api/drafts' : `/api/drafts?status=${status}`
      return api.get<Draft[]>(path)
    },
  })
}

export function usePublishDraft() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (draftId: string) =>
      api.post<Draft>(`/api/drafts/${draftId}/publish`, { confirmed: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: DRAFTS_QUERY_KEY }),
  })
}
