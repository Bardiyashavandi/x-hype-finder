export function DigestsPage() {
  return (
    <div>
      <h1 className="text-xl font-semibold text-gray-100">Digests</h1>
      <p className="mt-2 text-sm text-gray-400">
        The digest run history and on-demand "Run digest" action will live here — wiring to{' '}
        <code className="rounded bg-surface-raised px-1 py-0.5">GET /api/digests</code> and{' '}
        <code className="rounded bg-surface-raised px-1 py-0.5">POST /api/digests/run</code> comes
        in step 3.
      </p>
    </div>
  )
}
