import type { SignalStrength } from '../../api/types'
import { Card } from '../ui/Card'

interface SignalStrengthCardProps {
  signal: SignalStrength
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-lg font-semibold text-gray-100">{value}</p>
    </div>
  )
}

export function SignalStrengthCard({ signal }: SignalStrengthCardProps) {
  return (
    <Card accent="pipeline">
      <h3 className="mb-3 text-xs font-medium uppercase tracking-wide text-pipeline">
        Signal strength
      </h3>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Total relevant" value={signal.total_relevant_count} />
        <Stat label="Distinct authors" value={signal.distinct_author_count} />
        <Stat label="Last 24h" value={signal.posts_last_24h} />
        <Stat label="Last 7d" value={signal.posts_last_7d} />
      </div>
      {signal.most_recent_post_at && (
        <p className="mt-3 text-xs text-gray-500">
          Most recent: {new Date(signal.most_recent_post_at).toLocaleString()}
        </p>
      )}
    </Card>
  )
}
