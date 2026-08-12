import type { ReactNode } from 'react'

// Status semantics from specs/003-web-dashboard/plan.md §3: green =
// published/kept/success, amber = held/pending (matches the README
// diagrams' gate-node amber), red = failed/error. `pipeline`/`agent` reuse
// the same two accent colors Card does, for non-status pills (e.g. a
// recurrence-signal or run-type badge) that still want the brand palette.
export type BadgeTone = 'success' | 'pending' | 'error' | 'neutral' | 'pipeline' | 'agent'

interface BadgeProps {
  tone?: BadgeTone
  children: ReactNode
}

const TONE_CLASSES: Record<BadgeTone, string> = {
  success: 'bg-status-success/15 text-status-success border-status-success/40',
  pending: 'bg-status-pending/15 text-status-pending border-status-pending/40',
  error: 'bg-status-error/15 text-status-error border-status-error/40',
  neutral: 'bg-surface text-gray-400 border-surface-border',
  pipeline: 'bg-pipeline-bg text-pipeline border-pipeline-border',
  agent: 'bg-agent-bg text-agent border-agent-border',
}

export function Badge({ tone = 'neutral', children }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  )
}
