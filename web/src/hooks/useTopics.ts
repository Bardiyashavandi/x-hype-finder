import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { Topic, TopicCreateRequest } from '../api/types'

export const TOPICS_QUERY_KEY = ['topics'] as const

export function useTopics() {
  return useQuery({
    queryKey: TOPICS_QUERY_KEY,
    queryFn: () => api.get<Topic[]>('/api/topics'),
  })
}

export function useAddTopic() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: TopicCreateRequest) => api.post<Topic>('/api/topics', payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TOPICS_QUERY_KEY }),
  })
}

export function useRemoveTopic() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (topicId: string) => api.delete<Topic>(`/api/topics/${topicId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TOPICS_QUERY_KEY }),
  })
}
