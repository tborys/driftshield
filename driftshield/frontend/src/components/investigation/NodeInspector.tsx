import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { RiskFlagBadge } from './RiskFlagBadge'
import type { GraphNode } from '../../types/graph'

interface NodeInspectorProps {
  node: GraphNode | null
}

export function NodeInspector({ node }: NodeInspectorProps) {
  if (!node) {
    return (
      <div className="p-4 text-muted-foreground text-sm">
        Select a node in the graph to inspect it.
      </div>
    )
  }

  return (
    <div className="p-4 space-y-4 overflow-y-auto">
      <div>
        <h3 className="font-semibold text-lg">{node.action || 'Unknown action'}</h3>
        <div className="flex items-center gap-2 mt-1">
          <Badge variant="secondary">{node.event_type}</Badge>
          <span className="text-sm text-muted-foreground">#{node.sequence_num}</span>
          {node.is_inflection && (
            <Badge variant="outline" className="border-orange-500 text-orange-600">
              Inflection Node
            </Badge>
          )}
        </div>
      </div>

      <Separator />

      {node.risk_flags.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Risk Flags</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {node.risk_flags.map((flag) => (
              <RiskFlagBadge key={flag} flag={flag} expanded />
            ))}
          </CardContent>
        </Card>
      )}

      {node.inputs && Object.keys(node.inputs).length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Inputs</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted p-2 rounded overflow-x-auto">
              {JSON.stringify(node.inputs, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}

      {node.outputs && Object.keys(node.outputs).length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Outputs</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted p-2 rounded overflow-x-auto">
              {JSON.stringify(node.outputs, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}

      {node.metadata && Object.keys(node.metadata).length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Metadata</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted p-2 rounded overflow-x-auto">
              {JSON.stringify(node.metadata, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
