import { type FormEvent, useState } from 'react'

import { Button } from '../ui/Button'

interface RunFormProps {
  defaultLookbackHours: number | undefined
  loading: boolean
  onSubmit: (phrases: string[], excludeTerms: string[]) => void
}

export function RunForm({ defaultLookbackHours, loading, onSubmit }: RunFormProps) {
  const [phrases, setPhrases] = useState<string[]>([''])
  const [excludeTerms, setExcludeTerms] = useState('')

  const updatePhrase = (index: number, value: string) => {
    setPhrases((current) => current.map((phrase, i) => (i === index ? value : phrase)))
  }

  const addPhraseRow = () => setPhrases((current) => [...current, ''])
  const removePhraseRow = (index: number) =>
    setPhrases((current) => current.filter((_, i) => i !== index))

  const canSubmit = phrases.some((phrase) => phrase.trim().length > 0) && !loading

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    const cleanPhrases = phrases.map((phrase) => phrase.trim()).filter(Boolean)
    const cleanExcludeTerms = excludeTerms
      .split(',')
      .map((term) => term.trim())
      .filter(Boolean)
    onSubmit(cleanPhrases, cleanExcludeTerms)
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-3 rounded-lg border border-surface-border bg-surface-raised p-4"
    >
      <div>
        <label className="mb-1 block text-xs text-gray-400">Problem-describing phrases</label>
        <div className="space-y-2">
          {phrases.map((phrase, index) => (
            <div key={index} className="flex gap-2">
              <input
                value={phrase}
                onChange={(event) => updatePhrase(index, event.target.value)}
                placeholder={`e.g. "can't find sublet"`}
                className="flex-1 rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-gray-100 outline-none focus:border-agent"
              />
              {phrases.length > 1 && (
                <Button type="button" variant="ghost" onClick={() => removePhraseRow(index)}>
                  ✕
                </Button>
              )}
            </div>
          ))}
        </div>
        <Button type="button" variant="ghost" className="mt-1 px-0" onClick={addPhraseRow}>
          + Add phrase
        </Button>
      </div>

      <div>
        <label className="mb-1 block text-xs text-gray-400">
          Exclude terms (comma-separated, optional)
        </label>
        <input
          value={excludeTerms}
          onChange={(event) => setExcludeTerms(event.target.value)}
          className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-gray-100 outline-none focus:border-agent"
        />
      </div>

      {defaultLookbackHours !== undefined && (
        <p className="text-xs text-gray-500">Looks back {defaultLookbackHours}h by default.</p>
      )}

      <Button type="submit" variant="primary" disabled={!canSubmit} loading={loading}>
        Run validation
      </Button>
    </form>
  )
}
