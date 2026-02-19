import { useCallback, useMemo } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap,
  useNodesState, useEdgesState,
  type Node, type Edge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { GraphNodeComponent, type GraphNodeData } from './GraphNode'
import type { GraphResponse } from '../../types/graph'

interface LineageGraphProps {
  graph: GraphResponse
  onNodeSelect: (nodeId: string | null) => void
  selectedNodeId: string | null
}

const nodeTypes = { custom: GraphNodeComponent }

export function LineageGraph({ graph, onNodeSelect, selectedNodeId }: LineageGraphProps) {
  const initialNodes: Node[] = useMemo(
    () =>
      graph.nodes.map((node, index) => ({
        id: node.id,
        type: 'custom',
        position: { x: 250, y: index * 120 },
        data: {
          label: node.action || node.event_type,
          eventType: node.event_type,
          action: node.action,
          riskFlags: node.risk_flags,
          isInflection: node.is_inflection,
        } satisfies GraphNodeData,
        selected: node.id === selectedNodeId,
      })),
    [graph.nodes, selectedNodeId],
  )

  const initialEdges: Edge[] = useMemo(
    () =>
      graph.edges.map((edge, index) => ({
        id: `e-${index}`,
        source: edge.source,
        target: edge.target,
        animated: false,
      })),
    [graph.edges],
  )

  const [nodes, , onNodesChange] = useNodesState(initialNodes)
  const [edges, , onEdgesChange] = useEdgesState(initialEdges)

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeSelect(node.id)
    },
    [onNodeSelect],
  )

  const onPaneClick = useCallback(() => {
    onNodeSelect(null)
  }, [onNodeSelect])

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  )
}
