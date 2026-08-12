import type { EvalStage, EvalStageReport } from '../api/types'
import { Badge } from '../components/ui/Badge'
import { Card } from '../components/ui/Card'
import { Spinner } from '../components/ui/Spinner'
import { useEvalReport } from '../hooks/useEval'

// Same order/labels as `eval report`'s CLI output (src/cli/eval.py's
// `_print_report`, which iterates `list(EvalStage)`).
const STAGE_LABELS: Record<EvalStage, string> = {
  filter: 'Filter',
  detect: 'Detect',
  cluster: 'Cluster',
  summarize: 'Summarize',
  draft: 'Draft Post',
  digest: 'Digest',
}
const STAGE_ORDER: EvalStage[] = ['filter', 'detect', 'cluster', 'summarize', 'draft', 'digest']

function StageStat({ stage, report }: { stage: EvalStage; report: EvalStageReport | null }) {
  return (
    <Card>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="font-medium text-gray-100">{STAGE_LABELS[stage]}</h3>
        {stage === 'digest' && <Badge tone="agent">SC-011 KPI</Badge>}
      </div>
      {report === null && <p className="text-sm text-gray-500">No labels yet.</p>}
      {report?.kind === 'binary' && (
        <p className="text-sm text-gray-300">
          <span className="text-lg font-semibold text-gray-100">
            {((100 * (report.correct ?? 0)) / (report.total || 1)).toFixed(1)}%
          </span>{' '}
          accuracy
          <span className="text-gray-500"> ({report.correct}/{report.total})</span>
        </p>
      )}
      {report?.kind === 'rating' && (
        <p className="text-sm text-gray-300">
          <span className="text-lg font-semibold text-gray-100">{report.avg?.toFixed(2)}</span>{' '}
          avg rating
          <span className="text-gray-500"> (n={report.n})</span>
        </p>
      )}
    </Card>
  )
}

export function EvalPage() {
  const { data, isPending, isError } = useEvalReport()

  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold text-gray-100">Eval</h1>

      {isPending && (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Spinner size="sm" /> Loading eval report…
        </div>
      )}
      {isError && <p className="text-sm text-status-error">Failed to load the eval report.</p>}

      {data && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {STAGE_ORDER.map((stage) => (
            <StageStat key={stage} stage={stage} report={data.report[stage]} />
          ))}
        </div>
      )}
    </div>
  )
}
