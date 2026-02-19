import { Badge } from '@/components/ui/badge'

const FLAG_DESCRIPTIONS: Record<string, string> = {
  assumption_mutation: 'An assumption was changed or contradicted during the decision path.',
  policy_divergence: 'The agent deviated from an established policy or rule.',
  constraint_violation: 'A hard constraint was breached.',
  context_contamination: 'Values from one context were misapplied to another.',
  coverage_gap: 'The output references fewer items than the input provided.',
}

interface RiskFlagBadgeProps {
  flag: string
  expanded?: boolean
}

export function RiskFlagBadge({ flag, expanded = false }: RiskFlagBadgeProps) {
  return (
    <div>
      <Badge variant="destructive">{flag.replace(/_/g, ' ')}</Badge>
      {expanded && (
        <p className="text-sm text-muted-foreground mt-1">
          {FLAG_DESCRIPTIONS[flag] || 'Unknown risk flag.'}
        </p>
      )}
    </div>
  )
}
