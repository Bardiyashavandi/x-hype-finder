import { useState } from 'react'

import { ApiError } from '../api/client'
import { RunForm } from '../components/idea-validate/RunForm'
import { SignalStrengthCard } from '../components/idea-validate/SignalStrengthCard'
import { ThemeCard } from '../components/idea-validate/ThemeCard'
import { VerdictCard } from '../components/idea-validate/VerdictCard'
import { Spinner } from '../components/ui/Spinner'
import { useToast } from '../components/ui/Toast'
import {
  useIdeaValidateDefaults,
  useIdeaValidateJobPolling,
  useStartIdeaValidateRun,
} from '../hooks/useIdeaValidate'

export function IdeaValidationPage() {
  const { data: defaults } = useIdeaValidateDefaults()
  const startRun = useStartIdeaValidateRun()
  const [jobId, setJobId] = useState<string | null>(null)
  const { showToast } = useToast()

  const jobQuery = useIdeaValidateJobPolling(jobId)
  const job = jobQuery.data
  const running = jobId !== null && (!job || job.status === 'running')

  const handleSubmit = (phrases: string[], excludeTerms: string[]) => {
    startRun.mutate(
      { phrases, exclude_terms: excludeTerms },
      {
        onSuccess: (accepted) => setJobId(accepted.job_id),
        onError: (error) => {
          showToast(
            error instanceof ApiError ? error.message : 'Failed to start the run.',
            'error',
          )
        },
      },
    )
  }

  const readout = job?.status === 'completed' ? job.readout : null

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-gray-100">Idea Validation</h1>

      <RunForm
        defaultLookbackHours={defaults?.default_lookback_hours}
        loading={startRun.isPending || running}
        onSubmit={handleSubmit}
      />

      {running && (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Spinner size="sm" /> Running — this can take a few minutes…
        </div>
      )}

      {job?.status === 'failed' && (
        <p className="text-sm text-status-error">{job.error ?? 'The run failed.'}</p>
      )}

      {readout && (
        <div className="space-y-4">
          {readout.fetch_error && (
            <div className="rounded-md border border-status-error/40 bg-status-error/10 p-3 text-sm text-status-error">
              {readout.fetch_error}
            </div>
          )}

          {readout.verdict && <VerdictCard verdict={readout.verdict} />}

          <SignalStrengthCard signal={readout.signal_strength} />

          {readout.themes.length === 0 ? (
            <p className="text-sm text-gray-400">No meaningful signal found for this query.</p>
          ) : (
            <div className="space-y-3">
              <h2 className="text-sm font-medium text-gray-300">
                Themes ({readout.themes.length})
              </h2>
              {readout.themes.map((theme, index) => (
                <ThemeCard key={index} theme={theme} rank={index + 1} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
