export function IdeaValidationPage() {
  return (
    <div>
      <h1 className="text-xl font-semibold text-gray-100">Idea Validation</h1>
      <p className="mt-2 text-sm text-gray-400">
        The run form, Verdict card, signal-strength numbers, and themes will render here — wiring
        to <code className="rounded bg-surface-raised px-1 py-0.5">POST /api/idea-validate</code>{' '}
        and its job-polling endpoint comes in step 3.
      </p>
    </div>
  )
}
