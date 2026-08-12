import { Card } from '../ui/Card'

interface VerdictCardProps {
  verdict: string
}

// Pink-accented (accent="agent") — visually says "this came from the LLM
// stage" the same way the README architecture diagram does
// (specs/003-web-dashboard/plan.md §3).
export function VerdictCard({ verdict }: VerdictCardProps) {
  return (
    <Card accent="agent">
      <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-agent">Verdict</h3>
      <p className="text-sm text-gray-100">{verdict}</p>
    </Card>
  )
}
