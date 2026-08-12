import type { ReactNode } from 'react'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
}

export function Modal({ open, onClose, title, children, footer }: ModalProps) {
  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-md rounded-lg border border-surface-border bg-surface-raised p-6 shadow-xl"
      >
        <div className="mb-4 flex items-start justify-between">
          <h2 className="text-base font-semibold text-gray-100">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-gray-500 transition-colors hover:text-gray-300"
          >
            ✕
          </button>
        </div>
        <div className="text-sm text-gray-300">{children}</div>
        {footer && <div className="mt-6 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  )
}
