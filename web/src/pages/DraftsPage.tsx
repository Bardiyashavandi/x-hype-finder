export function DraftsPage() {
  return (
    <div>
      <h1 className="text-xl font-semibold text-gray-100">Drafts</h1>
      <p className="mt-2 text-sm text-gray-400">
        Held/published drafts and the publish confirmation modal will live here — wiring to{' '}
        <code className="rounded bg-surface-raised px-1 py-0.5">GET /api/drafts</code> and{' '}
        <code className="rounded bg-surface-raised px-1 py-0.5">POST /api/drafts/:id/publish</code>{' '}
        comes in step 3.
      </p>
    </div>
  )
}
