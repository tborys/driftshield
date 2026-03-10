export interface ExplanationPayload {
  reason: string
  confidence: number | null
  evidence_refs: string[]
}

export interface SessionProvenance {
  source_session_id: string | null
  source_path: string | null
  parser_version: string | null
  ingested_at: string | null
}

export interface GraphNode {
  id: string
  event_type: string
  action: string | null
  sequence_num: number
  risk_flags: string[]
  risk_explanations: Record<string, ExplanationPayload>
  is_inflection: boolean
  inflection_explanation: ExplanationPayload | null
  inputs: Record<string, unknown> | null
  outputs: Record<string, unknown> | null
  metadata: Record<string, unknown> | null
  parent_node_id: string | null
}

export interface GraphEdge {
  source: string
  target: string
}

export interface GraphResponse {
  session_id: string
  provenance: SessionProvenance | null
  nodes: GraphNode[]
  edges: GraphEdge[]
}
