import type { HTMLAttributes } from 'react'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  // 'pipeline' for deterministic-pipeline content, 'agent' for AI-derived
  // content (specs/003-web-dashboard/plan.md §3) — e.g. the Idea Validation
  // Verdict card gets `accent="agent"` to visually say "this came from the
  // LLM stage," the same way the README's architecture diagram does.
  accent?: 'pipeline' | 'agent' | 'none'
}

const ACCENT_CLASSES: Record<NonNullable<CardProps['accent']>, string> = {
  pipeline: 'border-pipeline-border',
  agent: 'border-agent-border',
  none: 'border-surface-border',
}

export function Card({ accent = 'none', className = '', children, ...rest }: CardProps) {
  return (
    <div
      {...rest}
      className={`rounded-lg border bg-surface-raised p-4 ${ACCENT_CLASSES[accent]} ${className}`}
    >
      {children}
    </div>
  )
}
