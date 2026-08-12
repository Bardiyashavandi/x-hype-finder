import type { Draft, DraftStatus } from '../../api/types'
import { Badge, type BadgeTone } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'

// Status semantics per specs/003-web-dashboard/plan.md §3: green =
// published, amber = held/pending, red = failed.
const STATUS_TONE: Record<DraftStatus, BadgeTone> = {
  held_manual: 'pending',
  held_below_threshold: 'pending',
  published_manual: 'success',
  published_auto: 'success',
  published_manual_override: 'success',
  publish_failed: 'error',
}

const STATUS_LABEL: Record<DraftStatus, string> = {
  held_manual: 'Held (manual)',
  held_below_threshold: 'Held (below threshold)',
  published_manual: 'Published (manual)',
  published_auto: 'Published (auto)',
  published_manual_override: 'Published (override)',
  publish_failed: 'Publish failed',
}

interface DraftCardProps {
  draft: Draft
  onPublish: (draft: Draft) => void
}

export function DraftCard({ draft, onPublish }: DraftCardProps) {
  return (
    <Card accent="agent">
      <div className="mb-2 flex items-start justify-between gap-4">
        <Badge tone={STATUS_TONE[draft.status]}>{STATUS_LABEL[draft.status]}</Badge>
        <span className="whitespace-nowrap text-xs text-gray-500">
          confidence {draft.confidence_score}
        </span>
      </div>
      <p className="text-sm text-gray-200">{draft.draft_text}</p>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs text-gray-500">
          created {new Date(draft.created_at).toLocaleString()}
          {draft.published_at && (
            <> · published {new Date(draft.published_at).toLocaleString()}</>
          )}
        </div>
        {draft.status === 'held_manual' && (
          <Button variant="primary" onClick={() => onPublish(draft)}>
            Mark published
          </Button>
        )}
      </div>
      {draft.tweet_url && (
        <a
          href={draft.tweet_url}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-block text-xs text-pipeline hover:underline"
        >
          View on X →
        </a>
      )}
      {draft.publish_error && (
        <p className="mt-2 text-xs text-status-error">Error: {draft.publish_error}</p>
      )}
    </Card>
  )
}
