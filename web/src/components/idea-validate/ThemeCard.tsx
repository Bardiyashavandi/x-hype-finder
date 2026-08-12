import type { ValidationTheme } from '../../api/types'
import { Badge, type BadgeTone } from '../ui/Badge'
import { Card } from '../ui/Card'

interface ThemeCardProps {
  theme: ValidationTheme
  rank: number
}

const RECURRENCE_TONE: Record<string, BadgeTone> = {
  isolated: 'neutral',
  emerging: 'pending',
  recurring: 'success',
}

export function ThemeCard({ theme, rank }: ThemeCardProps) {
  return (
    <Card accent="agent" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="neutral">#{rank}</Badge>
        <Badge tone={RECURRENCE_TONE[theme.recurrence_signal] ?? 'neutral'}>
          {theme.recurrence_signal}
        </Badge>
        <span className="text-xs text-gray-500">
          {theme.cluster_post_count} posts · {theme.distinct_author_count} authors
        </span>
      </div>
      <p className="text-sm text-gray-100">{theme.summary}</p>
      <p className="text-xs text-gray-400">&ldquo;{theme.representative_ask}&rdquo;</p>
      <div>
        <p className="mb-1 text-xs font-medium text-gray-500">Examples</p>
        <ul className="space-y-1">
          {theme.example_post_texts.map((text, index) => (
            <li key={index} className="text-xs text-gray-400">
              {text}
            </li>
          ))}
        </ul>
      </div>
    </Card>
  )
}
