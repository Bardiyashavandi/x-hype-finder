import type { DigestTheme } from '../../api/types'
import { Badge, type BadgeTone } from '../ui/Badge'
import { Card } from '../ui/Card'

interface ThemeCardProps {
  theme: DigestTheme
}

function confidenceTone(score: number): BadgeTone {
  if (score >= 60) return 'success'
  if (score >= 20) return 'pending'
  return 'neutral'
}

export function ThemeCard({ theme }: ThemeCardProps) {
  return (
    <Card accent="pipeline" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="pipeline">rank {theme.rank}</Badge>
        <Badge tone={confidenceTone(theme.confidence_score)}>
          confidence {theme.confidence_score}
        </Badge>
        {theme.is_spike && (
          <Badge tone="pending">spike ×{theme.spike_ratio?.toFixed(1) ?? '?'}</Badge>
        )}
        <span className="text-xs text-gray-500">{theme.cluster_post_count} posts</span>
      </div>
      <p className="text-sm text-gray-100">{theme.summary}</p>
      <p className="text-xs text-gray-400">{theme.rationale}</p>

      <div>
        <p className="mb-1 text-xs font-medium text-gray-500">
          Examples ({theme.example_posts.length})
        </p>
        <ul className="space-y-1">
          {theme.example_posts.map((post) => (
            <li key={post.id} className="text-xs text-gray-400">
              <span className="text-gray-300">@{post.author_handle}</span>: {post.text}
            </li>
          ))}
        </ul>
      </div>

      {theme.source_posts && (
        <div>
          <p className="mb-1 text-xs font-medium text-gray-500">
            All clustered posts ({theme.source_posts.length})
          </p>
          <ul className="space-y-1">
            {theme.source_posts.map((post) => (
              <li key={post.id} className="text-xs text-gray-400">
                <span className="text-gray-300">@{post.author_handle}</span>: {post.text}
                {post.is_example && <span className="ml-1 text-gray-600">(example)</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  )
}
