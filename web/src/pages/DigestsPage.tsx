import { Link } from 'react-router-dom'

import type { DigestStatus } from '../api/types'
import { RunDigestButton } from '../components/digests/RunDigestButton'
import { Badge, type BadgeTone } from '../components/ui/Badge'
import { Card } from '../components/ui/Card'
import { Spinner } from '../components/ui/Spinner'
import { useDigests } from '../hooks/useDigests'

const STATUS_TONE: Record<DigestStatus, BadgeTone> = {
  completed: 'success',
  partial: 'pending',
  failed: 'error',
}

export function DigestsPage() {
  const { data: digests, isPending, isError } = useDigests()

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-gray-100">Digests</h1>
        <RunDigestButton />
      </div>

      {isPending && (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Spinner size="sm" /> Loading digests…
        </div>
      )}
      {isError && <p className="text-sm text-status-error">Failed to load digests.</p>}
      {digests && digests.length === 0 && (
        <p className="text-sm text-gray-400">No digests yet — run one to get started.</p>
      )}

      <div className="space-y-3">
        {digests?.map((digest) => (
          <Link key={digest.id} to={`/digests/${digest.id}`}>
            <Card accent="pipeline" className="transition-colors hover:border-pipeline">
              <div className="flex items-center gap-2">
                <Badge tone={STATUS_TONE[digest.status]}>{digest.status}</Badge>
                <span className="text-xs uppercase text-gray-500">
                  {digest.run_type.replace('_', ' ')}
                </span>
              </div>
              <p className="mt-1 text-xs text-gray-500">
                started {new Date(digest.started_at).toLocaleString()}
                {digest.completed_at && (
                  <> · completed {new Date(digest.completed_at).toLocaleString()}</>
                )}
              </p>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  )
}
