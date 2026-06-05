import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { Badge } from '@/components/ui/badge'

export interface GraphNodeData {
  label: string
  eventType: string
  action: string | null
  riskFlags: string[]
  isInflection: boolean
}

export const GraphNodeComponent = memo(({ data, selected }: NodeProps) => {
  const nodeData = data as unknown as GraphNodeData
  const hasRisk = nodeData.riskFlags.length > 0
  return (
    <div
      className={`
        px-3 py-2 rounded-md border bg-card text-card-foreground text-sm min-w-[160px] shadow-md
        ${nodeData.isInflection ? 'border-[var(--ds-warning)] ring-2 ring-[rgba(255,206,122,0.25)]' : 'border-border'}
        ${selected ? 'ring-2 ring-primary' : ''}
        ${hasRisk && !nodeData.isInflection ? 'border-[var(--ds-danger)]' : ''}
      `}
    >
      <Handle type="target" position={Position.Top} className="!bg-[var(--ds-accent)]" />
      <div className="flex items-center gap-1 mb-1">
        <Badge variant="secondary" className="text-xs">{nodeData.eventType}</Badge>
        {nodeData.isInflection && (
          <Badge variant="outline" className="text-xs border-[var(--ds-warning)] text-[var(--ds-warning)]">
            inflection
          </Badge>
        )}
      </div>
      <div className="font-medium truncate">{nodeData.action || '\u2014'}</div>
      {nodeData.riskFlags.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {nodeData.riskFlags.map((flag) => (
            <Badge key={flag} variant="destructive" className="text-xs">{flag}</Badge>
          ))}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-[var(--ds-accent)]" />
    </div>
  )
})

GraphNodeComponent.displayName = 'GraphNodeComponent'
