// TypeScript mirrors of src/web/schemas.py's Pydantic response/request
// models — kept as plain interfaces (not re-derived/generated) so a
// backend field rename is a visible diff here too.

// ---------------------------------------------------------------------------
// Topics
// ---------------------------------------------------------------------------

export interface Topic {
  id: string
  name: string
  x_handles: string[]
  status: string
  first_tracked_at: string
  in_observation_period: boolean
}

export interface TopicCreateRequest {
  name: string
  handles?: string[]
}

// ---------------------------------------------------------------------------
// Drafts
// ---------------------------------------------------------------------------

export type DraftStatus =
  | 'held_manual'
  | 'published_manual'
  | 'held_below_threshold'
  | 'published_auto'
  | 'publish_failed'
  | 'published_manual_override'

export interface Draft {
  id: string
  theme_id: string
  draft_text: string
  confidence_score: number
  status: DraftStatus
  created_at: string
  published_at: string | null
  publish_error: string | null
  tweet_id: string | null
  tweet_url: string | null
}

// ---------------------------------------------------------------------------
// Eval
// ---------------------------------------------------------------------------

export type EvalStage = 'filter' | 'detect' | 'cluster' | 'summarize' | 'draft' | 'digest'

export interface EvalStageReport {
  kind: 'binary' | 'rating'
  correct: number | null
  total: number | null
  avg: number | null
  n: number | null
}

export interface EvalReportResponse {
  report: Record<EvalStage, EvalStageReport | null>
}

// ---------------------------------------------------------------------------
// Digests
// ---------------------------------------------------------------------------

export type DigestStatus = 'completed' | 'partial' | 'failed'
export type DigestRunType = 'scheduled' | 'on_demand'
export type DigestTopicOutcome =
  | 'themes_present'
  | 'no_significant_activity'
  | 'all_filtered_as_noise'
  | 'fetch_error'
  | 'incomplete_rate_limited'

export interface DigestSummary {
  id: string
  run_type: DigestRunType
  status: DigestStatus
  started_at: string
  completed_at: string | null
}

export interface SourcePost {
  id: string
  author_handle: string
  text: string
  posted_at: string
  filter_outcome: string
  is_example: boolean
}

export interface DigestTheme {
  id: string
  rank: number
  confidence_score: number
  is_spike: boolean
  spike_ratio: number | null
  cluster_post_count: number
  summary: string
  rationale: string
  example_posts: SourcePost[]
  source_posts: SourcePost[] | null
}

export interface DigestTopicResult {
  topic_id: string
  topic_name: string
  outcome: DigestTopicOutcome
  error_detail: string | null
  themes: DigestTheme[]
  hidden_theme_count: number
  excluded_posts: SourcePost[] | null
}

export interface DigestDetail {
  id: string
  status: DigestStatus
  run_type: DigestRunType
  started_at: string
  completed_at: string | null
  topics: DigestTopicResult[]
}

export interface DigestRunRequest {
  topic_name?: string | null
}

export interface JobAccepted {
  job_id: string
}

export type JobStatus = 'running' | 'completed' | 'failed'

export interface DigestJobStatus {
  status: JobStatus
  digest_id: string | null
  error: string | null
}

// ---------------------------------------------------------------------------
// Idea Validation
// ---------------------------------------------------------------------------

export interface IdeaValidateDefaults {
  default_lookback_hours: number
}

export interface IdeaValidateRunRequest {
  phrases: string[]
  exclude_terms?: string[]
  since?: string | null
  until?: string | null
}

export interface SignalStrength {
  total_relevant_count: number
  distinct_author_count: number
  most_recent_post_at: string | null
  oldest_post_at: string | null
  posts_last_24h: number
  posts_last_7d: number
}

export interface ValidationTheme {
  summary: string
  representative_ask: string
  recurrence_signal: string
  cluster_post_count: number
  distinct_author_count: number
  example_post_texts: string[]
}

export interface ValidationReadout {
  phrases: string[]
  exclude_terms: string[]
  generated_at: string
  verdict: string | null
  fetch_error: string | null
  signal_strength: SignalStrength
  themes: ValidationTheme[]
}

export interface IdeaValidateJobStatus {
  status: JobStatus
  readout: ValidationReadout | null
  error: string | null
}
