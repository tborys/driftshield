export interface ValidationRecord {
  id: string
  session_id: string
  target_type: string
  target_ref: string
  verdict: 'accept' | 'reject' | 'needs_review'
  confidence: number | null
  reviewer: string
  notes: string | null
  metadata_json: Record<string, unknown> | null
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
  shareable?: boolean
}
