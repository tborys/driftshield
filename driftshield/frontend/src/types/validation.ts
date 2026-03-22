export type ReviewOutcomeLabel =
  | 'useful_failure'
  | 'noise'
  | 'true_inflection'
  | 'wrong_inflection'
  | 'needs_follow_up'

export interface ReviewOutcomeMetadata {
  label: ReviewOutcomeLabel
  target_type?: string
}

export interface ValidationMetadata {
  review_outcome?: ReviewOutcomeMetadata
  flag_name?: string
  node_id?: string
  signature_hash?: string
  [key: string]: unknown
}

export interface ValidationRecord {
  id: string
  session_id: string
  target_type: string
  target_ref: string
  verdict: 'accept' | 'reject' | 'needs_review'
  confidence: number | null
  reviewer: string
  notes: string | null
  metadata_json: ValidationMetadata | null
  shareable: boolean
  created_at: string
}

export interface ValidationCreatePayload {
  target_type: string
  target_ref: string
  verdict: 'accept' | 'reject' | 'needs_review'
  reviewer: string
  confidence?: number
  notes?: string
  metadata_json?: ValidationMetadata
  shareable?: boolean
}
