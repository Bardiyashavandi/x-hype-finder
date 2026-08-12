import { useState } from 'react'
import { useParams } from 'react-router-dom'

import type { DigestStatus, DigestTopicOutcome } from '../api/types'
import { FullToggle } from '../components/digests/FullToggle'
import { ThemeCard } from '../components/digests/ThemeCard'
import { Badge, type BadgeTone } from '../components/ui/Badge'
import { Card } from '../components/ui/Card'
import { Spinner } from '../components/ui/Spinner'
import { useDigestDetail } from '../hooks/useDigests'

const STATUS_TONE: Record<DigestStatus, BadgeTone> = {
  completed: 'success',
  partial: 'pending',
  failed: 'error',
}

const OUTCOME_LABEL: Record<DigestTopicOutcome, string> = {
  themes_present: 'Themes present',
  no_significant_activity: 'No significant activity',
  all_filtered_as_noise: 'All filtered as noise',
  fetch_error: 'Fetch error',
  incomplete_rate_limited: 'Incomplete (rate limited)',
}

const OUTCOME_TONE: Record<DigestTopicOutcome, BadgeTone> = {
  themes_present: 'success',
  no_significant_activity: 'neutral',
  all_filtered_as_noise: 'neutral',
  fetch_error: 'error',
  incomplete_rate_limited: 'pending',
}

export function DigestDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [full, setFull] = useState(false)
  const { data: digest, isPending, isError } = useDigestDetail(id ?? '', full)

  if (isPending) {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-400">
        <Spinner size="sm" /> Loading digest…
      </div>
    )
  }

  if (isError || !digest) {
    return <p className="text-sm text-status-error">Failed to load this digest.</p>
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="break-all text-xl font-semibold text-gray-100">Digest {digest.id}</h1>
          <div className="mt-1 flex items-center gap-2">
            <Badge tone={STATUS_TONE[digest.status]}>{digest.status}</Badge>
            <span className="text-xs text-gray-500">
              started {new Date(digest.started_at).toLocaleString()}
            </span>
          </div>
        </div>
        <FullToggle full={full} onChange={setFull} />
      </div>

      <div className="space-y-6">
        {digest.topics.map((topicResult) => (
          <section key={topicResult.topic_id}>
            <div className="mb-2 flex items-center gap-2">
              <h2 className="text-lg font-medium text-gray-100">{topicResult.topic_name}</h2>
              <Badge tone={OUTCOME_TONE[topicResult.outcome]}>
                {OUTCOME_LABEL[topicResult.outcome]}
              </Badge>
            </div>
            {topicResult.error_detail && (
              <p className="mb-2 text-xs text-status-error">{topicResult.error_detail}</p>
            )}

            <div className="space-y-3">
              {topicResult.themes.map((theme) => (
                <ThemeCard key={theme.id} theme={theme} />
              ))}
            </div>

            {topicResult.hidden_theme_count > 0 && (
              <p className="mt-2 text-xs text-gray-500">
                {topicResult.hidden_theme_count} additional low-confidence theme
                {topicResult.hidden_theme_count === 1 ? '' : 's'} not shown — toggle full detail
                to see everything.
              </p>
            )}

            {full && topicResult.excluded_posts && topicResult.excluded_posts.length > 0 && (
              <Card className="mt-3">
                <p className="mb-1 text-xs font-medium text-gray-500">
                  Excluded/unclustered posts ({topicResult.excluded_posts.length})
                </p>
                <ul className="space-y-1">
                  {topicResult.excluded_posts.map((post) => (
                    <li key={post.id} className="text-xs text-gray-400">
                      <span className="text-gray-300">@{post.author_handle}</span>: {post.text}{' '}
                      <span className="text-gray-600">[{post.filter_outcome}]</span>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </section>
        ))}
      </div>
    </div>
  )
}
