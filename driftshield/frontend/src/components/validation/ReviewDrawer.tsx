import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCreateSessionValidation, useSessionValidations } from '@/api/sessions'
import type { GraphNode } from '@/types/graph'
import type { ReviewOutcomeLabel, ValidationRecord } from '@/types/validation'

interface ReviewDrawerProps {
  open: boolean
  sessionId: string
  node: GraphNode | null
  onClose: () => void
}

const reviewOutcomeLabels: ReviewOutcomeLabel[] = [
  'useful_failure',
  'noise',
  'true_inflection',
  'wrong_inflection',
  'needs_follow_up',
]

function isValidationForNode(validation: ValidationRecord, nodeId: string) {
  if (validation.target_ref === nodeId) {
    return true
  }

  const [targetNodeId] = validation.target_ref.split(':')
  if (targetNodeId === nodeId) {
    return true
  }

  const metadataNodeId = typeof validation.metadata_json?.node_id === 'string'
    ? validation.metadata_json.node_id
    : null

  return metadataNodeId === nodeId
}

function prettifyReviewOutcome(label: ReviewOutcomeLabel) {
  return label.replace(/_/g, ' ')
}

function defaultOutcomeForNode(node: GraphNode | null): ReviewOutcomeLabel {
  if (!node) {
    return 'needs_follow_up'
  }

  if (node.is_inflection) {
    return 'true_inflection'
  }

  return node.risk_flags.length > 0 ? 'useful_failure' : 'needs_follow_up'
}

function verdictForOutcome(label: ReviewOutcomeLabel): 'accept' | 'reject' | 'needs_review' {
  switch (label) {
    case 'useful_failure':
    case 'true_inflection':
      return 'accept'
    case 'noise':
    case 'wrong_inflection':
      return 'reject'
    case 'needs_follow_up':
      return 'needs_review'
  }
}

export function ReviewDrawer({ open, sessionId, node, onClose }: ReviewDrawerProps) {
  const [reviewer, setReviewer] = useState('analyst')
  const [verdict, setVerdict] = useState<'accept' | 'reject' | 'needs_review'>('accept')
  const [reviewOutcome, setReviewOutcome] = useState<ReviewOutcomeLabel>('needs_follow_up')
  const [notes, setNotes] = useState('')
  const [confidence, setConfidence] = useState('0.8')
  const [shareable, setShareable] = useState(true)
  const [saveStatus, setSaveStatus] = useState<string | null>(null)

  const { data: validations = [], isLoading } = useSessionValidations(sessionId)
  const createValidation = useCreateSessionValidation(sessionId)

  useEffect(() => {
    if (!open) return

    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }

    window.addEventListener('keydown', onEscape)
    return () => window.removeEventListener('keydown', onEscape)
  }, [open, onClose])

  useEffect(() => {
    if (open && node) {
      const defaultOutcome = defaultOutcomeForNode(node)
      setReviewOutcome(defaultOutcome)
      setVerdict(verdictForOutcome(defaultOutcome))
      setTimeout(() => {
        const input = document.getElementById('reviewer-input') as HTMLInputElement | null
        input?.focus()
      }, 0)
    }
  }, [open, node])

  const parsedConfidence = Number(confidence)
  const confidenceInvalid = confidence.length > 0 && (Number.isNaN(parsedConfidence) || parsedConfidence < 0 || parsedConfidence > 1)
  const canSave = Boolean(node) && reviewer.trim().length > 0 && !confidenceInvalid

  const nodeValidations = useMemo(
    () => validations.filter((v) => (node ? isValidationForNode(v, node.id) : false)),
    [node, validations],
  )

  const save = async () => {
    if (!node || !canSave) return

    setSaveStatus(null)

    try {
      await createValidation.mutateAsync({
        target_type: node.is_inflection ? 'inflection' : 'risk_flag',
        target_ref: node.risk_flags.length > 0 ? `${node.id}:${node.risk_flags[0]}` : node.id,
        reviewer: reviewer.trim(),
        verdict,
        notes: notes || undefined,
        confidence: Number.isNaN(parsedConfidence) ? undefined : parsedConfidence,
        metadata_json: {
          node_id: node.id,
          ...(node.risk_flags.length > 0 ? { flag_name: node.risk_flags[0] } : {}),
          review_outcome: {
            label: reviewOutcome,
            target_type: node.is_inflection ? 'inflection' : 'risk_flag',
          },
        },
        shareable,
      })

      setNotes('')
      setSaveStatus('Review outcome saved.')
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Review outcome save failed.'
      setSaveStatus(message)
    }
  }

  if (!open) return null

  return (
    <div
      className="w-[360px] border-l bg-background h-full overflow-y-auto p-4 space-y-4"
      role="dialog"
      aria-label="Node review"
      aria-modal="false"
    >
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
            <Input id="reviewer-input" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
          </div>

          <div className="space-y-2">
            <label className="text-xs text-muted-foreground">Dogfood review outcome</label>
            <div className="flex gap-2 flex-wrap">
              {reviewOutcomeLabels.map((option) => (
                <Button
                  key={option}
                  size="sm"
                  variant={reviewOutcome === option ? 'default' : 'outline'}
                  onClick={() => {
                    setReviewOutcome(option)
                    setVerdict(verdictForOutcome(option))
                  }}
                >
                  {prettifyReviewOutcome(option)}
                </Button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-xs text-muted-foreground">Verdict</label>
            <div className="rounded-md border px-3 py-2 text-sm">
              <span className="font-medium">{verdict}</span>
              <span className="text-muted-foreground"> {' '}derived from the selected dogfood outcome</span>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-xs text-muted-foreground">Confidence (0-1)</label>
            <Input
              value={confidence}
              onChange={(e) => setConfidence(e.target.value)}
              aria-invalid={confidenceInvalid}
            />
            {confidenceInvalid && (
              <p className="text-xs text-destructive">Confidence must be a number between 0 and 1.</p>
            )}
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={shareable} onChange={(e) => setShareable(e.target.checked)} />
            Include in evaluation/training exports
          </label>

          <div className="space-y-2">
            <label className="text-xs text-muted-foreground">Notes</label>
            <textarea
              className="w-full min-h-20 border rounded-md p-2 text-sm"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add quick analyst note"
            />
          </div>

          <Button onClick={save} disabled={createValidation.isPending || !canSave}>
            {createValidation.isPending ? 'Saving...' : 'Save review outcome'}
          </Button>

          {saveStatus && (
            <p className={`text-xs ${saveStatus === 'Review outcome saved.' ? 'text-emerald-600' : 'text-destructive'}`} aria-live="polite">
              {saveStatus}
            </p>
          )}

          <div className="pt-2 border-t">
            <h4 className="text-sm font-medium mb-2">Review history</h4>
            {isLoading ? (
              <p className="text-sm text-muted-foreground">Loading...</p>
            ) : nodeValidations.length === 0 ? (
              <p className="text-sm text-muted-foreground">No reviews yet for this node.</p>
            ) : (
              <ul className="space-y-2">
                {nodeValidations.map((v) => {
                  const rawReviewOutcomeLabel = v.metadata_json?.review_outcome?.label
                  const reviewOutcomeLabel =
                    typeof rawReviewOutcomeLabel === 'string' ? rawReviewOutcomeLabel as ReviewOutcomeLabel : null
                  return (
                    <li key={v.id} className="text-xs border rounded p-2">
                      <p>
                        <span className="font-medium">{reviewOutcomeLabel ? prettifyReviewOutcome(reviewOutcomeLabel) : v.verdict}</span>
                        {' '}by {v.reviewer}
                      </p>
                      <p className="text-muted-foreground">{new Date(v.created_at).toLocaleString()}</p>
                      {v.notes ? <p>{v.notes}</p> : null}
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  )
}
