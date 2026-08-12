import { useState } from 'react'

import { ApiError } from '../api/client'
import type { Draft, DraftStatus } from '../api/types'
import { DraftCard } from '../components/drafts/DraftCard'
import { PublishConfirmModal } from '../components/drafts/PublishConfirmModal'
import { Spinner } from '../components/ui/Spinner'
import { useToast } from '../components/ui/Toast'
import { useDrafts, usePublishDraft } from '../hooks/useDrafts'

const STATUS_FILTERS: Array<{ value: DraftStatus | 'all'; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'held_manual', label: 'Held (manual)' },
  { value: 'held_below_threshold', label: 'Held (below threshold)' },
  { value: 'published_manual', label: 'Published (manual)' },
  { value: 'published_auto', label: 'Published (auto)' },
  { value: 'published_manual_override', label: 'Published (override)' },
  { value: 'publish_failed', label: 'Publish failed' },
]

export function DraftsPage() {
  const [statusFilter, setStatusFilter] = useState<DraftStatus | 'all'>('all')
  const { data: drafts, isPending, isError } = useDrafts(statusFilter)
  const publishDraft = usePublishDraft()
  const { showToast } = useToast()
  const [publishTarget, setPublishTarget] = useState<Draft | null>(null)

  const handleConfirmPublish = () => {
    if (!publishTarget) return
    publishDraft.mutate(publishTarget.id, {
      onSuccess: () => {
        showToast('Draft marked as published.')
        setPublishTarget(null)
      },
      onError: (error) => {
        showToast(
          error instanceof ApiError ? error.message : 'Failed to publish draft.',
          'error',
        )
        setPublishTarget(null)
      },
    })
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-gray-100">Drafts</h1>
        <select
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value as DraftStatus | 'all')}
          className="rounded-md border border-surface-border bg-surface-raised px-3 py-1.5 text-sm text-gray-200 outline-none focus:border-pipeline"
        >
          {STATUS_FILTERS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {isPending && (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Spinner size="sm" /> Loading drafts…
        </div>
      )}
      {isError && <p className="text-sm text-status-error">Failed to load drafts.</p>}
      {drafts && drafts.length === 0 && <p className="text-sm text-gray-400">No drafts found.</p>}

      <div className="space-y-3">
        {drafts?.map((draft) => (
          <DraftCard key={draft.id} draft={draft} onPublish={setPublishTarget} />
        ))}
      </div>

      <PublishConfirmModal
        draft={publishTarget}
        loading={publishDraft.isPending}
        onConfirm={handleConfirmPublish}
        onCancel={() => setPublishTarget(null)}
      />
    </div>
  )
}
