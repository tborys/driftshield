import { useCallback, useEffect, useMemo } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap,
  useNodesState, useEdgesState,
  type Node, type Edge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import Dagre from '@dagrejs/dagre'
import { GraphNodeComponent, type GraphNodeData } from './GraphNode'
import type { GraphResponse } from '../../types/graph'

interface LineageGraphProps {
  graph: GraphResponse
  onNodeSelect: (nodeId: string | null) => void
  selectedNodeId: string | null
}

const nodeTypes = { custom: GraphNodeComponent }

function layoutGraph(graph: GraphResponse, selectedNodeId: string | null): { nodes: Node[]; edges: Edge[] } {
  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'TB', nodesep: 50, ranksep: 80 })

  graph.nodes.forEach((node) => {
    g.setNode(node.id, { width: 200, height: 80 })
  })

  graph.edges.forEach((edge) => {
    g.setEdge(edge.source, edge.target)
  })

  Dagre.layout(g)

  const nodes: Node[] = graph.nodes.map((node) => {
    const pos = g.node(node.id)
    return {
      id: node.id,
      type: 'custom',
      position: { x: pos.x - 100, y: pos.y - 40 },
      data: {
        label: node.action || node.event_type,
        eventType: node.event_type,
        action: node.action,
        riskFlags: node.risk_flags,
        isInflection: node.is_inflection,
      } satisfies GraphNodeData,
      selected: node.id === selectedNodeId,
    }
  })

  const edges: Edge[] = graph.edges.map((edge, index) => ({
    id: `e-${index}`,
    source: edge.source,
    target: edge.target,
  }))

  return { nodes, edges }
}

export function LineageGraph({ graph, onNodeSelect, selectedNodeId }: LineageGraphProps) {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => layoutGraph(graph, selectedNodeId),
    [graph, selectedNodeId],
  )

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)

  useEffect(() => {
    setNodes(initialNodes)
  }, [initialNodes, setNodes])

  useEffect(() => {
    setEdges(initialEdges)
  }, [initialEdges, setEdges])

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
