// A `ConfirmDialog` in its "type to confirm" mode (specs/003-web-dashboard/plan.md
// §0.A, §2) — mirrors the CLI's `_confirm_already_posted` gate: this only
// records that the draft was already posted to X by hand, it never calls
// the X API itself (`mark_published()`, src/cli/drafts.py). A plain
// two-button dialog would be too easy to click through for an action that
// asserts something happened in the real world, so this uses the stronger
// mode `ConfirmDialog` offers via `confirmText`.

import type { Draft } from '../../api/types'
import { ConfirmDialog } from '../ui/ConfirmDialog'

interface PublishConfirmModalProps {
  draft: Draft | null
  loading: boolean
  onConfirm: () => void
  onCancel: () => void
}

const CONFIRM_PHRASE = 'PUBLISHED'

export function PublishConfirmModal({
  draft,
  loading,
  onConfirm,
  onCancel,
}: PublishConfirmModalProps) {
  return (
    <ConfirmDialog
      open={draft !== null}
      title="Mark draft as published"
      description={
        <div className="space-y-2">
          <p>
            This will mark the draft below as{' '}
            <strong className="text-gray-100">PUBLISHED</strong> without posting it to X — it
            only records that you already posted it yourself.
          </p>
          {draft && (
            <p className="rounded-md border border-surface-border bg-surface p-2 text-xs text-gray-400">
              {draft.draft_text}
            </p>
          )}
        </div>
      }
      confirmLabel="Mark published"
      confirmText={CONFIRM_PHRASE}
      loading={loading}
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  )
}
