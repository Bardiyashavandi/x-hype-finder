export function TopicsPage() {
  return (
    <div>
      <h1 className="text-xl font-semibold text-gray-100">Topics</h1>
      <p className="mt-2 text-sm text-gray-400">
        Tracked topics/tickers will be listed and managed here — wiring to{' '}
        <code className="rounded bg-surface-raised px-1 py-0.5">GET/POST /api/topics</code> and{' '}
        <code className="rounded bg-surface-raised px-1 py-0.5">DELETE /api/topics/:id</code> comes
        in step 3.
      </p>
    </div>
  )
}
