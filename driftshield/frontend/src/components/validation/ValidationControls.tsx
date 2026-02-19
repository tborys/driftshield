import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import type { GraphNode } from '../../types/graph'

interface ValidationControlsProps {
  node: GraphNode
}

export function ValidationControls({ node }: ValidationControlsProps) {
  const [inflectionValidation, setInflectionValidation] = useState<'confirmed' | 'rejected' | null>(null)
  const [riskValidations, setRiskValidations] = useState<Record<string, 'validated' | 'disputed' | 'false_positive'>>({})

  const handleInflectionValidation = (decision: 'confirmed' | 'rejected') => {
    setInflectionValidation(decision)
  }

  const handleRiskValidation = (flag: string, decision: 'validated' | 'disputed' | 'false_positive') => {
    setRiskValidations(prev => ({ ...prev, [flag]: decision }))
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Analyst Validation</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {node.is_inflection && (
          <div>
            <p className="text-sm font-medium mb-2">Inflection Node</p>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant={inflectionValidation === 'confirmed' ? 'default' : 'outline'}
                onClick={() => handleInflectionValidation('confirmed')}
              >
                Confirm
              </Button>
              <Button
                size="sm"
                variant={inflectionValidation === 'rejected' ? 'destructive' : 'outline'}
                onClick={() => handleInflectionValidation('rejected')}
              >
                Reject
              </Button>
            </div>
            {inflectionValidation && (
              <p className="text-xs text-muted-foreground mt-1">
                {inflectionValidation === 'confirmed' ? 'Confirmed as inflection point.' : 'Rejected as inflection point.'}
              </p>
            )}
          </div>
        )}

        {node.risk_flags.length > 0 && (
          <>
            {node.is_inflection && <Separator />}
            <div>
              <p className="text-sm font-medium mb-2">Risk Flags</p>
              {node.risk_flags.map((flag) => (
                <div key={flag} className="mb-2">
                  <p className="text-xs font-medium mb-1">{flag.replace(/_/g, ' ')}</p>
                  <div className="flex gap-1">
                    <Button
                      size="sm" variant={riskValidations[flag] === 'validated' ? 'default' : 'outline'}
                      className="text-xs h-7"
                      onClick={() => handleRiskValidation(flag, 'validated')}
                    >
                      Validate
                    </Button>
                    <Button
                      size="sm" variant={riskValidations[flag] === 'disputed' ? 'secondary' : 'outline'}
                      className="text-xs h-7"
                      onClick={() => handleRiskValidation(flag, 'disputed')}
                    >
                      Dispute
                    </Button>
                    <Button
                      size="sm" variant={riskValidations[flag] === 'false_positive' ? 'destructive' : 'outline'}
                      className="text-xs h-7"
                      onClick={() => handleRiskValidation(flag, 'false_positive')}
                    >
                      False positive
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {!node.is_inflection && node.risk_flags.length === 0 && (
          <p className="text-sm text-muted-foreground">No validation actions available for this node.</p>
        )}
      </CardContent>
    </Card>
  )
}
