import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCreateSessionValidation, useSessionValidations } from '@/api/sessions'
import type { GraphNode } from '@/types/graph'

interface ReviewDrawerProps {
  open: boolean
  sessionId: string
  node: GraphNode | null
  onClose: () => void
}

const verdictOptions: Array<'accept' | 'reject' | 'needs_review'> = ['accept', 'reject', 'needs_review']

export function ReviewDrawer({ open, sessionId, node, onClose }: ReviewDrawerProps) {
  const [reviewer, setReviewer] = useState('analyst')
  const [verdict, setVerdict] = useState<'accept' | 'reject' | 'needs_review'>('accept')
  const [notes, setNotes] = useState('')
  const [confidence, setConfidence] = useState('0.8')

  const { data: validations = [], isLoading } = useSessionValidations(sessionId)
  const createValidation = useCreateSessionValidation(sessionId)

  const nodeValidations = useMemo(
    () => validations.filter((v) => (node ? v.target_ref.includes(node.id) : false)),
    [node, validations],
  )

  const save = async () => {
    if (!node) return

    await createValidation.mutateAsync({
      target_type: node.is_inflection ? 'inflection' : 'risk_flag',
      target_ref: node.risk_flags.length > 0 ? `${node.id}:${node.risk_flags[0]}` : node.id,
      reviewer,
      verdict,
      notes: notes || undefined,
      confidence: Number.isNaN(Number(confidence)) ? undefined : Number(confidence),
      shareable: false,
    })
    setNotes('')
  }

  if (!open) return null

  return (
    <div className="w-[360px] border-l bg-background h-full overflow-y-auto p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">Review</h3>
        <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
      </div>

      {!node ? (
        <p className="text-sm text-muted-foreground">Select a node to review.</p>
      ) : (
        <>
          <div className="text-sm">
            <p className="font-medium">{node.action || 'Unknown action'}</p>
            <p className="text-muted-foreground">Node #{node.sequence_num}</p>
          </div>

          <div className="space-y-2">
            <label className="text-xs text-muted-foreground">Reviewer</label>
            <Input value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
          </div>

          <div className="space-y-2">
            <label className="text-xs text-muted-foreground">Verdict</label>
            <div className="flex gap-2 flex-wrap">
              {verdictOptions.map((option) => (
                <Button
                  key={option}
                  size="sm"
                  variant={verdict === option ? 'default' : 'outline'}
                  onClick={() => setVerdict(option)}
                >
                  {option}
                </Button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-xs text-muted-foreground">Confidence (0-1)</label>
            <Input value={confidence} onChange={(e) => setConfidence(e.target.value)} />
          </div>

          <div className="space-y-2">
            <label className="text-xs text-muted-foreground">Notes</label>
            <textarea
              className="w-full min-h-20 border rounded-md p-2 text-sm"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add quick analyst note"
            />
          </div>

          <Button onClick={save} disabled={createValidation.isPending}>
            {createValidation.isPending ? 'Saving...' : 'Save validation'}
          </Button>

          <div className="pt-2 border-t">
            <h4 className="text-sm font-medium mb-2">Validation history</h4>
            {isLoading ? (
              <p className="text-sm text-muted-foreground">Loading...</p>
            ) : nodeValidations.length === 0 ? (
              <p className="text-sm text-muted-foreground">No validations yet for this node.</p>
            ) : (
              <ul className="space-y-2">
                {nodeValidations.map((v) => (
                  <li key={v.id} className="text-xs border rounded p-2">
                    <p><span className="font-medium">{v.verdict}</span> by {v.reviewer}</p>
                    <p className="text-muted-foreground">{new Date(v.created_at).toLocaleString()}</p>
                    {v.notes ? <p>{v.notes}</p> : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  )
}
