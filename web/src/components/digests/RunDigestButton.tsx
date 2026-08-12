// Starts an on-demand digest run (`POST /api/digests/run`, a background
// job — src/web/jobs.py) and polls it via `useJobPolling` until it settles,
// then invalidates the digest list and navigates to the finished digest
// (specs/003-web-dashboard/plan.md §1 "Background jobs", §2).

import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { DIGESTS_QUERY_KEY, useDigestJobPolling, useStartDigestRun } from '../../hooks/useDigests'
import { useTopics } from '../../hooks/useTopics'
import { Button } from '../ui/Button'
import { useToast } from '../ui/Toast'

const ALL_TOPICS_VALUE = ''

export function RunDigestButton() {
  const { data: topics } = useTopics()
  const startRun = useStartDigestRun()
  const queryClient = useQueryClient()
  const [jobId, setJobId] = useState<string | null>(null)
  const [topicName, setTopicName] = useState<string>(ALL_TOPICS_VALUE)
  const { showToast } = useToast()
  const navigate = useNavigate()

  const jobQuery = useDigestJobPolling(jobId)
  const jobData = jobQuery.data

  useEffect(() => {
    if (!jobData) return
    if (jobData.status === 'completed') {
      queryClient.invalidateQueries({ queryKey: DIGESTS_QUERY_KEY })
      showToast('Digest run completed.')
      if (jobData.digest_id) {
        navigate(`/digests/${jobData.digest_id}`)
      }
      setJobId(null)
    } else if (jobData.status === 'failed') {
      showToast(jobData.error ?? 'Digest run failed.', 'error')
      setJobId(null)
    }
  }, [jobData, queryClient, showToast, navigate])

  const running = jobId !== null

  const handleRun = () => {
    startRun.mutate(topicName || null, {
      onSuccess: (accepted) => setJobId(accepted.job_id),
      onError: (error) => {
        showToast(error instanceof ApiError ? error.message : 'Failed to start digest run.', 'error')
      },
    })
  }

  return (
    <div className="flex items-center gap-2">
      <select
        value={topicName}
        onChange={(event) => setTopicName(event.target.value)}
        disabled={running || startRun.isPending}
        className="rounded-md border border-surface-border bg-surface-raised px-3 py-1.5 text-sm text-gray-200 outline-none focus:border-pipeline"
      >
        <option value={ALL_TOPICS_VALUE}>All active topics</option>
        {topics?.map((topic) => (
          <option key={topic.id} value={topic.name}>
            {topic.name}
          </option>
        ))}
      </select>
      <Button
        variant="primary"
        onClick={handleRun}
        disabled={running || startRun.isPending}
        loading={running || startRun.isPending}
      >
        {running ? 'Running…' : 'Run digest'}
      </Button>
    </div>
  )
}
