import { useState, useMemo } from 'react'
import { LineageGraph } from './LineageGraph'
import { NodeInspector } from './NodeInspector'
import type { GraphResponse, GraphNode } from '../../types/graph'

interface InvestigationViewProps {
  graph: GraphResponse
}

export function InvestigationView({ graph }: InvestigationViewProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)

  const selectedNode: GraphNode | null = useMemo(
    () => graph.nodes.find((n) => n.id === selectedNodeId) ?? null,
    [graph.nodes, selectedNodeId],
  )

  return (
    <div className="flex h-[calc(100vh-57px)]">
      <div className="flex-1">
        <LineageGraph
          graph={graph}
          onNodeSelect={setSelectedNodeId}
          selectedNodeId={selectedNodeId}
        />
      </div>
      <div className="w-[400px] border-l overflow-y-auto">
        <NodeInspector node={selectedNode} />
      </div>
    </div>
  )
}
