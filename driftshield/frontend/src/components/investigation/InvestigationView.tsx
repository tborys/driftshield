import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { LineageGraph } from './LineageGraph'
import { NodeInspector } from './NodeInspector'
import { ReviewDrawer } from '../validation/ReviewDrawer'
import type { ExplanationPayload, GraphNode, GraphResponse } from '../../types/graph'

interface InvestigationViewProps {
  graph: GraphResponse
}

function formatConfidence(confidence: number | null) {
  if (confidence === null || Number.isNaN(confidence)) {
    return 'n/a'
  }

  return `${Math.round(confidence * 100)}%`
}

function sourceLabel(graph: GraphResponse) {
  const parser = graph.provenance?.parser_version ?? 'unknown parser'
  const path = graph.provenance?.source_path ?? 'unknown source'
  return `${parser} · ${path}`
}

function orderedRiskExplanationEntries(node: GraphNode) {
  const entries = Object.entries(node.risk_explanations)
  const explainedFlags = new Set<string>()
  const orderedEntries: Array<[string, ExplanationPayload]> = []

  node.risk_flags.forEach((flag) => {
    const explanation = node.risk_explanations[flag]
    if (!explanation) {
      return
    }

    explainedFlags.add(flag)
    orderedEntries.push([flag, explanation])
  })

  entries.forEach(([flag, explanation]) => {
    if (!explainedFlags.has(flag)) {
      orderedEntries.push([flag, explanation])
    }
  })

  return orderedEntries
}

function findPrimaryNarrative(node: GraphNode | null) {
  if (!node) {
    return null
  }

  const firstRiskExplanation = orderedRiskExplanationEntries(node)[0]
  if (firstRiskExplanation) {
    return {
      kind: 'risk' as const,
      label: firstRiskExplanation[0].replace(/_/g, ' '),
      explanation: firstRiskExplanation[1],
    }
  }

  if (node.inflection_explanation) {
    return {
      kind: 'inflection' as const,
      label: 'inflection',
      explanation: node.inflection_explanation,
    }
  }

  return null
}

function EvidenceSummary({ explanation }: { explanation: ExplanationPayload | null }) {
  if (!explanation) {
    return <p className="text-sm text-muted-foreground">No evidence refs were returned.</p>
  }

  if (explanation.evidence_refs.length === 0) {
    return <p className="text-sm text-muted-foreground">No evidence refs were attached to this explanation.</p>
  }

  return (
    <div className="flex flex-wrap gap-2">
      {explanation.evidence_refs.map((ref) => (
        <Badge key={ref} variant="secondary" className="font-mono text-[11px]">
          {ref}
        </Badge>
      ))}
    </div>
  )
}

export function InvestigationView({ graph }: InvestigationViewProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const selectedNode = useMemo(
    () => graph.nodes.find((n) => n.id === selectedNodeId) || null,
    [graph.nodes, selectedNodeId],
  )

  const flaggedNodes = useMemo(
    () => graph.nodes.filter((node) => node.risk_flags.length > 0),
    [graph.nodes],
  )

  const timelineNodes = useMemo(
    () => [...graph.nodes].sort((a, b) => a.sequence_num - b.sequence_num),
    [graph.nodes],
  )

  const primaryNarrative = findPrimaryNarrative(selectedNode)

  return (
    <div className="p-6 space-y-6">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_420px]">
        <Card className="min-h-[720px]">
          <CardHeader className="border-b">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <CardTitle>Investigation graph</CardTitle>
                <CardDescription>
                  Trace the decision path, select a node, and inspect its narrative and evidence.
                </CardDescription>
              </div>
              <div className="flex flex-wrap gap-2">
                <Badge variant="outline">{graph.nodes.length} nodes</Badge>
                <Badge variant="outline">{graph.edges.length} edges</Badge>
                <Badge variant={flaggedNodes.length > 0 ? 'destructive' : 'secondary'}>
                  {flaggedNodes.length} flagged
                </Badge>
                <Badge variant="outline">{sourceLabel(graph)}</Badge>
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-0 h-[640px]">
            <LineageGraph graph={graph} onNodeSelect={setSelectedNodeId} selectedNodeId={selectedNodeId} />
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <CardTitle className="text-base">Selected node narrative</CardTitle>
                  <CardDescription>
                    Human-readable explanation for the current decision point.
                  </CardDescription>
                </div>
                <Button size="sm" onClick={() => setDrawerOpen(true)} disabled={!selectedNode}>
                  Open review
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {!selectedNode ? (
                <p className="text-sm text-muted-foreground">Select a node to surface its narrative.</p>
              ) : !primaryNarrative ? (
                <p className="text-sm text-muted-foreground">
                  This node has no enriched narrative yet. Payload details may still be available below.
                </p>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={primaryNarrative.kind === 'risk' ? 'destructive' : 'outline'}>
                      {primaryNarrative.label}
                    </Badge>
                    <Badge variant="outline">{formatConfidence(primaryNarrative.explanation.confidence)}</Badge>
                  </div>
                  <p className="text-sm leading-6">{primaryNarrative.explanation.reason}</p>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Evidence refs</CardTitle>
              <CardDescription>Fast links to the structured evidence attached to the explanation.</CardDescription>
            </CardHeader>
            <CardContent>
              <EvidenceSummary explanation={primaryNarrative?.explanation ?? null} />
            </CardContent>
          </Card>

          <Card className="max-h-[420px] overflow-hidden">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Timeline</CardTitle>
              <CardDescription>
                Sequence view for the session, with flagged and inflection nodes called out.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 overflow-y-auto max-h-[320px] pr-1">
              {timelineNodes.map((node, index) => (
                <div key={node.id}>
                  <button
                    type="button"
                    className={`w-full rounded-lg border p-3 text-left transition-colors hover:bg-muted/40 ${
                      selectedNodeId === node.id ? 'border-primary bg-primary/5' : ''
                    }`}
                    onClick={() => setSelectedNodeId(node.id)}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">#{node.sequence_num}</Badge>
                        <Badge variant="secondary">{node.event_type}</Badge>
                        {node.risk_flags.length > 0 && (
                          <Badge variant="destructive">{node.risk_flags.length} risk flag{node.risk_flags.length > 1 ? 's' : ''}</Badge>
                        )}
                        {node.is_inflection && <Badge variant="outline">inflection</Badge>}
                      </div>
                    </div>
                    <div className="mt-2 text-sm font-medium">{node.action || 'Unknown action'}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {node.parent_node_id ? `Parent ${node.parent_node_id.slice(0, 8)}…` : 'Root node'}
                    </div>
                  </button>
                  {index < timelineNodes.length - 1 && <Separator className="my-3" />}
                </div>
              ))}
            </CardContent>
          </Card>

          <Card className="max-h-[720px] overflow-hidden">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Node inspector</CardTitle>
              <CardDescription>Structured payload, explanations and metadata for the selected node.</CardDescription>
            </CardHeader>
            <CardContent className="p-0 max-h-[620px] overflow-y-auto">
              <NodeInspector node={selectedNode} />
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="fixed inset-y-0 right-0 z-40">
        <ReviewDrawer
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          sessionId={graph.session_id}
          node={selectedNode}
        />
      </div>
    </div>
  )
}
