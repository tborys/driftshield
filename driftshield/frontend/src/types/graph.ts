export interface GraphNode {
  id: string
  event_type: string
  action: string | null
  sequence_num: number
  risk_flags: string[]
  is_inflection: boolean
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
  nodes: GraphNode[]
  edges: GraphEdge[]
}
