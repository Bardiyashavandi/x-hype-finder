import { useState } from 'react'

import { ApiError } from '../api/client'
import type { Topic } from '../api/types'
import { AddTopicModal } from '../components/topics/AddTopicModal'
import { TopicCard } from '../components/topics/TopicCard'
import { Button } from '../components/ui/Button'
import { ConfirmDialog } from '../components/ui/ConfirmDialog'
import { Spinner } from '../components/ui/Spinner'
import { useToast } from '../components/ui/Toast'
import { useAddTopic, useRemoveTopic, useTopics } from '../hooks/useTopics'

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

export function TopicsPage() {
  const { data: topics, isPending, isError } = useTopics()
  const addTopic = useAddTopic()
  const removeTopic = useRemoveTopic()
  const { showToast } = useToast()

  const [addOpen, setAddOpen] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [removeTarget, setRemoveTarget] = useState<Topic | null>(null)

  const handleAddSubmit = (name: string, handles: string[]) => {
    setAddError(null)
    addTopic.mutate(
      { name, handles },
      {
        onSuccess: (topic) => {
          setAddOpen(false)
          showToast(`Added topic "${topic.name}".`)
        },
        onError: (error) => setAddError(errorMessage(error, 'Failed to add topic.')),
      },
    )
  }

  const handleConfirmRemove = () => {
    if (!removeTarget) return
    const removedName = removeTarget.name
    removeTopic.mutate(removeTarget.id, {
      onSuccess: () => {
        showToast(`Removed topic "${removedName}".`)
        setRemoveTarget(null)
      },
      onError: (error) => {
        showToast(errorMessage(error, 'Failed to remove topic.'), 'error')
        setRemoveTarget(null)
      },
    })
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-100">Topics</h1>
        <Button variant="primary" onClick={() => setAddOpen(true)}>
          Add topic
        </Button>
      </div>

      {isPending && (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Spinner size="sm" /> Loading topics…
        </div>
      )}
      {isError && <p className="text-sm text-status-error">Failed to load topics.</p>}
      {topics && topics.length === 0 && (
        <p className="text-sm text-gray-400">No topics tracked yet — add one to get started.</p>
      )}

      <div className="space-y-3">
        {topics?.map((topic) => (
          <TopicCard key={topic.id} topic={topic} onRemove={setRemoveTarget} />
        ))}
      </div>

      <AddTopicModal
        open={addOpen}
        onClose={() => {
          setAddOpen(false)
          setAddError(null)
        }}
        onSubmit={handleAddSubmit}
        loading={addTopic.isPending}
        error={addError}
      />

      <ConfirmDialog
        open={removeTarget !== null}
        title="Remove topic"
        description={
          <>
            Remove <span className="font-medium text-gray-100">{removeTarget?.name}</span> from
            tracking? Its history is kept — you can re-add it later.
          </>
        }
        confirmLabel="Remove"
        danger
        loading={removeTopic.isPending}
        onConfirm={handleConfirmRemove}
        onCancel={() => setRemoveTarget(null)}
      />
    </div>
  )
}
