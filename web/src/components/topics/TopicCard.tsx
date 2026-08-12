import type { Topic } from '../../api/types'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'

interface TopicCardProps {
  topic: Topic
  onRemove: (topic: Topic) => void
}

export function TopicCard({ topic, onRemove }: TopicCardProps) {
  return (
    <Card accent="pipeline" className="flex items-start justify-between gap-4">
      <div>
        <div className="flex items-center gap-2">
          <h3 className="font-medium text-gray-100">{topic.name}</h3>
          {topic.in_observation_period && <Badge tone="pending">Observation period</Badge>}
        </div>
        {topic.x_handles.length > 0 && (
          <p className="mt-1 text-xs text-gray-400">
            {topic.x_handles.map((handle) => `@${handle}`).join(', ')}
          </p>
        )}
        <p className="mt-1 text-xs text-gray-500">
          Tracking since {new Date(topic.first_tracked_at).toLocaleDateString()}
        </p>
      </div>
      <Button variant="secondary" onClick={() => onRemove(topic)}>
        Remove
      </Button>
    </Card>
  )
}
