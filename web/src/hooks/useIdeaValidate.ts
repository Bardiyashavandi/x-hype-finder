import { useMutation, useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type {
  IdeaValidateDefaults,
  IdeaValidateJobStatus,
  IdeaValidateRunRequest,
  JobAccepted,
} from '../api/types'
import { useJobPolling } from './useJobPolling'

export function useIdeaValidateDefaults() {
  return useQuery({
    queryKey: ['idea-validate', 'defaults'],
    queryFn: () => api.get<IdeaValidateDefaults>('/api/idea-validate'),
  })
}

export function useStartIdeaValidateRun() {
  return useMutation({
    mutationFn: (payload: IdeaValidateRunRequest) =>
      api.post<JobAccepted>('/api/idea-validate', payload),
  })
}

export function useIdeaValidateJobPolling(jobId: string | null) {
  return useJobPolling<IdeaValidateJobStatus>(
    ['idea-validate', 'jobs', jobId],
    () => api.get<IdeaValidateJobStatus>(`/api/idea-validate/jobs/${jobId}`),
    { enabled: jobId !== null },
  )
}
