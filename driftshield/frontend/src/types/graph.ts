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
  node_kind: string | null
  event_type: string
  action: string | null
  summary: string | null
  confidence: number | null
  sequence_num: number
  risk_flags: string[]
  risk_explanations: Record<string, ExplanationPayload>
  evidence_refs: string[]
  is_inflection: boolean
  inflection_explanation: ExplanationPayload | null
  inputs: Record<string, unknown> | null
  outputs: Record<string, unknown> | null
  metadata: Record<string, unknown> | null
  parent_node_id: string | null
  parent_node_ids: string[]
  lineage_ambiguities: string[]
}

export interface GraphEdge {
  source: string
  target: string
  relationship: string
  confidence: number
  inferred: boolean
  reason: string | null
  evidence_refs: string[]
}

export interface GraphResponse {
  session_id: string
  provenance: SessionProvenance | null
  nodes: GraphNode[]
  edges: GraphEdge[]
}

type UnknownRecord = Record<string, unknown>

function asRecord(value: unknown): UnknownRecord | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }

  return value as UnknownRecord
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }

  return value.filter((item): item is string => typeof item === 'string')
}

function asNullableString(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

function asNullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function normalizeExplanationPayload(value: unknown): ExplanationPayload | null {
  const record = asRecord(value)
  if (!record) {
    return null
  }

  return {
    reason: typeof record.reason === 'string' ? record.reason : '',
    confidence: asNullableNumber(record.confidence),
    evidence_refs: asStringArray(record.evidence_refs),
  }
}

function normalizeRiskExplanations(value: unknown): Record<string, ExplanationPayload> {
  const record = asRecord(value)
  if (!record) {
    return {}
  }

  const entries = Object.entries(record)
    .map(([flag, explanation]) => {
      const normalizedExplanation = normalizeExplanationPayload(explanation)
      return normalizedExplanation ? [flag, normalizedExplanation] : null
    })
    .filter((entry): entry is [string, ExplanationPayload] => entry !== null)

  return Object.fromEntries(entries)
}

function normalizeSessionProvenance(value: unknown): SessionProvenance | null {
  const record = asRecord(value)
  if (!record) {
    return null
  }

  return {
    source_session_id: asNullableString(record.source_session_id),
    source_path: asNullableString(record.source_path),
    parser_version: asNullableString(record.parser_version),
    ingested_at: asNullableString(record.ingested_at),
  }
}

function normalizeNodePayload(value: unknown): Record<string, unknown> | null {
  return asRecord(value)
}

function normalizeGraphNode(value: unknown): GraphNode {
  const record = asRecord(value) ?? {}
  const parentNodeId = asNullableString(record.parent_node_id)
  const parentNodeIds = asStringArray(record.parent_node_ids)

  return {
    id: asNullableString(record.id) ?? '',
    node_kind: asNullableString(record.node_kind),
    event_type: asNullableString(record.event_type) ?? 'UNKNOWN',
    action: asNullableString(record.action),
    summary: asNullableString(record.summary),
    confidence: asNullableNumber(record.confidence),
    sequence_num: asNullableNumber(record.sequence_num) ?? 0,
    risk_flags: asStringArray(record.risk_flags),
    risk_explanations: normalizeRiskExplanations(record.risk_explanations),
    evidence_refs: asStringArray(record.evidence_refs),
    is_inflection: Boolean(record.is_inflection),
    inflection_explanation: normalizeExplanationPayload(record.inflection_explanation),
    inputs: normalizeNodePayload(record.inputs),
    outputs: normalizeNodePayload(record.outputs),
    metadata: normalizeNodePayload(record.metadata),
    parent_node_id: parentNodeId,
    parent_node_ids: parentNodeIds.length > 0 ? parentNodeIds : parentNodeId ? [parentNodeId] : [],
    lineage_ambiguities: asStringArray(record.lineage_ambiguities),
  }
}

function normalizeGraphEdge(value: unknown): GraphEdge {
  const record = asRecord(value) ?? {}

  return {
    source: asNullableString(record.source) ?? '',
    target: asNullableString(record.target) ?? '',
    relationship: asNullableString(record.relationship) ?? 'parent',
    confidence: asNullableNumber(record.confidence) ?? 1,
    inferred: Boolean(record.inferred),
    reason: asNullableString(record.reason),
    evidence_refs: asStringArray(record.evidence_refs),
  }
}

// Keep the investigation view resilient while richer lineage fields roll out across fixtures and persisted payloads.
export function normalizeGraphResponse(value: unknown): GraphResponse {
  const record = asRecord(value) ?? {}

  return {
    session_id: asNullableString(record.session_id) ?? '',
    provenance: normalizeSessionProvenance(record.provenance),
    nodes: Array.isArray(record.nodes) ? record.nodes.map(normalizeGraphNode) : [],
    edges: Array.isArray(record.edges) ? record.edges.map(normalizeGraphEdge) : [],
  }
}
