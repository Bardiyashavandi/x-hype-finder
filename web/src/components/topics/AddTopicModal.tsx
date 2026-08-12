import { useState } from 'react'

import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'

interface AddTopicModalProps {
  open: boolean
  onClose: () => void
  onSubmit: (name: string, handles: string[]) => void
  loading: boolean
  error: string | null
}

export function AddTopicModal({ open, onClose, onSubmit, loading, error }: AddTopicModalProps) {
  const [name, setName] = useState('')
  const [handles, setHandles] = useState('')

  if (!open) return null

  const handleClose = () => {
    setName('')
    setHandles('')
    onClose()
  }

  const handleSubmit = () => {
    const parsedHandles = handles
      .split(',')
      .map((handle) => handle.trim())
      .filter(Boolean)
    onSubmit(name.trim(), parsedHandles)
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Add topic"
      footer={
        <>
          <Button variant="secondary" onClick={handleClose} disabled={loading}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleSubmit}
            disabled={loading || name.trim().length === 0}
            loading={loading}
          >
            Add topic
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div>
          <label className="mb-1 block text-xs text-gray-400">Name</label>
          <input
            autoFocus
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder='e.g. "AI agents" or "$AAPL"'
            className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-gray-100 outline-none focus:border-pipeline"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-gray-400">
            X handles (comma-separated, optional)
          </label>
          <input
            value={handles}
            onChange={(event) => setHandles(event.target.value)}
            placeholder="aapl_news, appleinsider"
            className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-gray-100 outline-none focus:border-pipeline"
          />
        </div>
        {error && <p className="text-sm text-status-error">{error}</p>}
      </div>
    </Modal>
  )
}
