import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { RiskFlagBadge } from './RiskFlagBadge'
import type { ExplanationPayload, GraphNode } from '../../types/graph'

interface NodeInspectorProps {
  node: GraphNode | null
}

function hasPayloadData(payload: Record<string, unknown> | null) {
  if (payload === null) {
    return false
  }

  return Object.keys(payload).length > 0
}

function formatConfidence(confidence: number | null) {
  if (confidence === null || Number.isNaN(confidence)) {
    return 'Confidence unavailable'
  }

  return `${Math.round(confidence * 100)}% confidence`
}

function ExplanationCard({
  title,
  explanation,
}: {
  title: string
  explanation: ExplanationPayload
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm">{title}</CardTitle>
          <Badge variant="outline">{formatConfidence(explanation.confidence)}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm leading-6">{explanation.reason}</p>
        {explanation.evidence_refs.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">Evidence refs</div>
            <div className="flex flex-wrap gap-2">
              {explanation.evidence_refs.map((ref) => (
                <Badge key={ref} variant="secondary" className="font-mono text-[11px]">
                  {ref}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function NodeInspector({ node }: NodeInspectorProps) {
  if (!node) {
    return (
      <div className="p-4 text-muted-foreground text-sm">
        Select a node in the graph to inspect it.
      </div>
    )
  }

  const explanationEntries = Object.entries(node.risk_explanations)
  const hasInputs = hasPayloadData(node.inputs)
  const hasOutputs = hasPayloadData(node.outputs)
  const hasMetadata = hasPayloadData(node.metadata)
  const hasEvidenceContent =
    node.evidence_refs.length > 0 || explanationEntries.length > 0 || node.inflection_explanation !== null

  return (
    <div className="p-4 space-y-4 overflow-y-auto">
      <div>
        <h3 className="font-semibold text-lg">{node.action || 'Unknown action'}</h3>
        {node.summary && (
          <p className="mt-1 text-sm text-muted-foreground">{node.summary}</p>
        )}
        <div className="flex flex-wrap items-center gap-2 mt-1">
          <Badge variant="secondary">{node.event_type}</Badge>
          {node.node_kind && <Badge variant="outline">{node.node_kind}</Badge>}
          <span className="text-sm text-muted-foreground">#{node.sequence_num}</span>
          {node.is_inflection && (
            <Badge variant="outline" className="border-orange-500 text-orange-600">
              Inflection Node
            </Badge>
          )}
        </div>
      </div>

      <Separator />

      <Tabs defaultValue="narrative" className="w-full">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="narrative">Narrative</TabsTrigger>
          <TabsTrigger value="evidence">Evidence</TabsTrigger>
          <TabsTrigger value="payload">Payload</TabsTrigger>
        </TabsList>

        <TabsContent value="narrative" className="space-y-4 pt-2">
          {node.risk_flags.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Risk flags</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {node.risk_flags.map((flag) => (
                  <RiskFlagBadge key={flag} flag={flag} expanded />
                ))}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Lineage context</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div>
                {node.parent_node_ids.length === 0
                  ? 'Root node'
                  : `${node.parent_node_ids.length} parent link${node.parent_node_ids.length > 1 ? 's' : ''}`}
              </div>
              {node.parent_node_ids.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {node.parent_node_ids.map((parentId) => (
                    <Badge key={parentId} variant="outline" className="font-mono text-[11px]">
                      {parentId}
                    </Badge>
                  ))}
                </div>
              )}
              {node.lineage_ambiguities.length > 0 && (
                <div className="space-y-2">
                  <div className="text-xs font-medium text-muted-foreground">Lineage ambiguities</div>
                  <div className="flex flex-wrap gap-2">
                    {node.lineage_ambiguities.map((ambiguity) => (
                      <Badge key={ambiguity} variant="secondary">
                        {ambiguity.replace(/_/g, ' ')}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {explanationEntries.length > 0 ? (
            explanationEntries.map(([flag, explanation]) => (
              <ExplanationCard
                key={flag}
                title={`${flag.replace(/_/g, ' ')} explanation`}
                explanation={explanation}
              />
            ))
          ) : (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Risk narrative</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                No explicit risk explanation was returned for this node.
              </CardContent>
            </Card>
          )}

          {node.inflection_explanation && (
            <ExplanationCard title="Inflection explanation" explanation={node.inflection_explanation} />
          )}
        </TabsContent>

        <TabsContent value="evidence" className="space-y-4 pt-2">
          {!hasEvidenceContent ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Evidence trail</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                No evidence refs were returned for this node.
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Evidence refs</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {node.evidence_refs.length > 0 && (
                  <div className="space-y-2">
                    <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      Node evidence
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {node.evidence_refs.map((ref) => (
                        <Badge key={`node-${ref}`} variant="secondary" className="font-mono text-[11px]">
                          {ref}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                {explanationEntries.map(([flag, explanation]) => (
                  <div key={flag} className="space-y-2">
                    <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      {flag.replace(/_/g, ' ')}
                    </div>
                    {explanation.evidence_refs.length > 0 ? (
                      <div className="flex flex-wrap gap-2">
                        {explanation.evidence_refs.map((ref) => (
                          <Badge key={`${flag}-${ref}`} variant="outline" className="font-mono text-[11px]">
                            {ref}
                          </Badge>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">No evidence refs attached.</p>
                    )}
                  </div>
                ))}

                {node.inflection_explanation && (
                  <div className="space-y-2">
                    <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      Inflection
                    </div>
                    {node.inflection_explanation.evidence_refs.length > 0 ? (
                      <div className="flex flex-wrap gap-2">
                        {node.inflection_explanation.evidence_refs.map((ref) => (
                          <Badge key={`inflection-${ref}`} variant="outline" className="font-mono text-[11px]">
                            {ref}
                          </Badge>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">No evidence refs attached.</p>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="payload" className="space-y-4 pt-2">
          {hasInputs && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Inputs</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="text-xs bg-muted p-2 rounded overflow-x-auto whitespace-pre-wrap break-words">
                  {JSON.stringify(node.inputs, null, 2)}
                </pre>
              </CardContent>
            </Card>
          )}

          {hasOutputs && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Outputs</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="text-xs bg-muted p-2 rounded overflow-x-auto whitespace-pre-wrap break-words">
                  {JSON.stringify(node.outputs, null, 2)}
                </pre>
              </CardContent>
            </Card>
          )}

          {hasMetadata && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Metadata</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="text-xs bg-muted p-2 rounded overflow-x-auto whitespace-pre-wrap break-words">
                  {JSON.stringify(node.metadata, null, 2)}
                </pre>
              </CardContent>
            </Card>
          )}

          {!hasInputs && !hasOutputs && !hasMetadata && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Payload</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                No structured inputs, outputs or metadata were returned for this node.
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>

      <Separator />
      <p className="text-xs text-muted-foreground">Use the Review drawer to save analyst validation.</p>
    </div>
  )
}
