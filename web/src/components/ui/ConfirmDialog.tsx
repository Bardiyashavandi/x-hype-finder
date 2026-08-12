// Shared confirmation modal, reused for topic removal and draft publish
// (specs/003-web-dashboard/plan.md §2) — a real modal, explicit
// "type to confirm" or a two-button dialog, never a single "Confirm?"
// button one misclick away. `confirmText` switches on the stronger mode:
// matches the CLI's `_confirm_already_posted` gate philosophy for actions
// that assert something happened in the real world (draft publish), not
// just a reversible local change (topic removal, which uses the plain
// two-button mode).

import { type ReactNode, useState } from 'react'

import { Button } from './Button'
import { Modal } from './Modal'

interface ConfirmDialogProps {
  open: boolean
  title: string
  description: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
  /** When set, the confirm button stays disabled until the user types this
   * exact text. */
  confirmText?: string
  loading?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  danger = false,
  confirmText,
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const [typed, setTyped] = useState('')

  if (!open) return null

  const requiresTyping = confirmText !== undefined
  const canConfirm = !requiresTyping || typed === confirmText

  const handleCancel = () => {
    setTyped('')
    onCancel()
  }

  const handleConfirm = () => {
    setTyped('')
    onConfirm()
  }

  return (
    <Modal
      open={open}
      onClose={handleCancel}
      title={title}
      footer={
        <>
          <Button variant="secondary" onClick={handleCancel} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button
            variant={danger ? 'danger' : 'primary'}
            onClick={handleConfirm}
            disabled={!canConfirm || loading}
            loading={loading}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div>{description}</div>
        {requiresTyping && (
          <div>
            <label className="mb-1 block text-xs text-gray-400">
              Type <span className="font-mono text-gray-200">{confirmText}</span> to confirm
            </label>
            <input
              autoFocus
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-gray-100 outline-none focus:border-pipeline"
            />
          </div>
        )}
      </div>
    </Modal>
  )
}
