export interface SessionProvenance {
  source_session_id: string | null
  source_path: string | null
  parser_version: string | null
  ingested_at: string | null
}

export interface SessionSummary {
  id: string
  agent_id: string | null
  external_id: string | null
  status: string
  started_at: string
  ended_at: string | null
  risk_flag_count: number
  has_inflection: boolean
  recurrence_level: 'new' | 'recurring' | 'systemic' | null
  recurrence_probability: 'low' | 'medium' | 'high' | null
  recurrence_count: number | null
  provenance: SessionProvenance | null
}

export interface SessionDetail extends SessionSummary {
  total_events: number
  flagged_events: number
  risk_summary: Record<string, number>
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  per_page: number
  pages: number
}

export interface SessionListFilters {
  flaggedOnly?: boolean
  riskClass?: string
  source?: string
  sinceHours?: number
}

export interface ReportSummary {
  id: string
  report_type: string
  generated_at: string
  generated_by: string | null
}

export interface ReportDetail {
  id: string
  session_id: string
  report_type: string
  generated_at: string
  content_markdown: string
  content_json: Record<string, unknown>
  generated_by: string | null
}

export interface GraveyardSummary {
  path: string
  content_markdown: string
}
