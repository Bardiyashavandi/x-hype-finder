import { useParams } from 'react-router-dom'

export function DigestDetailPage() {
  const { id } = useParams<{ id: string }>()

  return (
    <div>
      <h1 className="text-xl font-semibold text-gray-100">Digest {id}</h1>
      <p className="mt-2 text-sm text-gray-400">
        Themes, confidence bands, and the <code className="rounded bg-surface-raised px-1 py-0.5">?full=</code>{' '}
        drill-down toggle will render here — wiring to{' '}
        <code className="rounded bg-surface-raised px-1 py-0.5">GET /api/digests/:id</code> comes
        in step 3.
      </p>
    </div>
  )
}
