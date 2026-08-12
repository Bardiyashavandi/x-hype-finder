export function EvalPage() {
  return (
    <div>
      <h1 className="text-xl font-semibold text-gray-100">Eval</h1>
      <p className="mt-2 text-sm text-gray-400">
        Per-stage accuracy/average-rating cards will render here — wiring to{' '}
        <code className="rounded bg-surface-raised px-1 py-0.5">GET /api/eval</code> comes in step
        3.
      </p>
    </div>
  )
}
