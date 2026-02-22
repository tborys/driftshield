import { useState, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { LineageGraph } from './LineageGraph'
import { NodeInspector } from './NodeInspector'
import { ReviewDrawer } from '../validation/ReviewDrawer'
import type { GraphResponse, GraphNode } from '../../types/graph'

interface InvestigationViewProps {
  graph: GraphResponse
}

export function InvestigationView({ graph }: InvestigationViewProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [reviewOpen, setReviewOpen] = useState(false)

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
        <div className="p-3 border-b flex items-center justify-between">
          <p className="text-sm text-muted-foreground">Node Inspector</p>
          <Button size="sm" onClick={() => setReviewOpen(true)} disabled={!selectedNode}>
            Open Review
          </Button>
        </div>
        <NodeInspector node={selectedNode} />
      </div>
      <ReviewDrawer
        open={reviewOpen}
        onClose={() => setReviewOpen(false)}
        sessionId={graph.session_id}
        node={selectedNode}
      />
    </div>
  )
}
