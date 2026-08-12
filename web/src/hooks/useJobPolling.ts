// Polls a background-job status endpoint (digest-run, idea-validate-run —
// specs/003-web-dashboard/plan.md §1 "Background jobs") every
// `POLL_INTERVAL_MS` while the job is still `running`, via react-query's
// `refetchInterval` — the natural fit the plan calls out (§2 "Server
// state") — stopping the moment the job settles into `completed`/`failed`.

import { useQuery, type UseQueryResult } from '@tanstack/react-query'

interface JobLike {
  status: 'running' | 'completed' | 'failed'
}

const POLL_INTERVAL_MS = 2000

export function useJobPolling<T extends JobLike>(
  queryKey: readonly unknown[],
  fetchJob: () => Promise<T>,
  options: { enabled?: boolean } = {},
): UseQueryResult<T> {
  return useQuery({
    queryKey,
    queryFn: fetchJob,
    enabled: options.enabled ?? true,
    refetchInterval: (query) =>
      query.state.data?.status === 'running' ? POLL_INTERVAL_MS : false,
  })
}
