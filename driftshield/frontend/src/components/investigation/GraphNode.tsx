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
  return (
    <div
      className={`
        px-3 py-2 rounded-md border bg-background text-sm min-w-[160px]
        ${nodeData.isInflection ? 'border-orange-500 ring-2 ring-orange-200' : 'border-border'}
        ${selected ? 'ring-2 ring-primary' : ''}
        ${nodeData.riskFlags.length > 0 ? 'border-red-300' : ''}
      `}
    >
      <Handle type="target" position={Position.Top} className="!bg-muted-foreground" />
      <div className="flex items-center gap-1 mb-1">
        <Badge variant="secondary" className="text-xs">{nodeData.eventType}</Badge>
        {nodeData.isInflection && <Badge variant="outline" className="text-xs border-orange-500">inflection</Badge>}
      </div>
      <div className="font-medium truncate">{nodeData.action || '\u2014'}</div>
      {nodeData.riskFlags.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {nodeData.riskFlags.map((flag) => (
            <Badge key={flag} variant="destructive" className="text-xs">{flag}</Badge>
          ))}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-muted-foreground" />
    </div>
  )
})

GraphNodeComponent.displayName = 'GraphNodeComponent'
