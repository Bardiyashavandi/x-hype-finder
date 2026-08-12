import { useMutation, useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { DigestDetail, DigestJobStatus, DigestSummary, JobAccepted } from '../api/types'
import { useJobPolling } from './useJobPolling'

export const DIGESTS_QUERY_KEY = ['digests'] as const

export function useDigests() {
  return useQuery({
    queryKey: DIGESTS_QUERY_KEY,
    queryFn: () => api.get<DigestSummary[]>('/api/digests'),
  })
}

export function useDigestDetail(digestId: string, full: boolean) {
  return useQuery({
    queryKey: [...DIGESTS_QUERY_KEY, digestId, { full }],
    queryFn: () => api.get<DigestDetail>(`/api/digests/${digestId}?full=${full}`),
    enabled: digestId.length > 0,
  })
}

export function useStartDigestRun() {
  // No `onSuccess` invalidation here — starting the job doesn't change the
  // digest list yet; `RunDigestButton` invalidates `DIGESTS_QUERY_KEY` once
  // the polled job actually completes.
  return useMutation({
    mutationFn: (topicName: string | null) =>
      api.post<JobAccepted>('/api/digests/run', { topic_name: topicName }),
  })
}

export function useDigestJobPolling(jobId: string | null) {
  return useJobPolling<DigestJobStatus>(
    [...DIGESTS_QUERY_KEY, 'jobs', jobId],
    () => api.get<DigestJobStatus>(`/api/digests/jobs/${jobId}`),
    { enabled: jobId !== null },
  )
}
