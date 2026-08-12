import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { EvalReportResponse } from '../api/types'

export function useEvalReport() {
  return useQuery({
    queryKey: ['eval'],
    queryFn: () => api.get<EvalReportResponse>('/api/eval'),
  })
}
