import { useMemo, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { SessionList } from '../components/sessions/SessionList'
import { useSessions } from '../api/sessions'
import type { SessionListFilters, SessionSummary } from '../types/session'

const DEFAULT_FILTERS: SessionListFilters = {
  flaggedOnly: false,
}

const RISK_OPTIONS = [
  { value: 'all', label: 'All risk classes' },
  { value: 'assumption_mutation', label: 'Assumption mutation' },
  { value: 'policy_divergence', label: 'Policy divergence' },
  { value: 'constraint_violation', label: 'Constraint violation' },
  { value: 'context_contamination', label: 'Context contamination' },
  { value: 'coverage_gap', label: 'Coverage gap' },
] as const

const SOURCE_OPTIONS = [
  { value: 'all', label: 'All sources' },
  { value: 'claude', label: 'Claude' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'codex', label: 'Codex' },
] as const

const WINDOW_OPTIONS = [
  { value: 'all', label: 'All time' },
  { value: '24', label: 'Last 24 hours' },
  { value: '72', label: 'Last 3 days' },
  { value: '168', label: 'Last 7 days' },
] as const

function sourceLabel(session: SessionSummary) {
  const path = (session.provenance?.source_path ?? '').toLowerCase()
  const parser = (session.provenance?.parser_version ?? '').toLowerCase()
  const signal = `${path} ${parser}`

  if (!signal.trim()) return null
  if (signal.includes('claude')) return 'Claude'
  if (signal.includes('openai')) return 'OpenAI'
  if (signal.includes('codex')) return 'Codex'
  return 'Other'
}

function sourceDisplayLabel(session: SessionSummary) {
  return sourceLabel(session) ?? 'Unknown source'
}

function parserLabel(session: SessionSummary) {
  return session.provenance?.parser_version ?? 'Unknown parser'
}

function latestIngestLabel(sessions: SessionSummary[]) {
  const latestIngest = sessions
    .flatMap((session) => (session.provenance?.ingested_at ? [session.provenance.ingested_at] : []))
    .sort((left, right) => new Date(right).getTime() - new Date(left).getTime())[0]

  if (!latestIngest) return 'No ingest timestamp'
  return new Date(latestIngest).toLocaleString()
}

function summariseCounts(items: string[]) {
  const counts = new Map<string, number>()
  items.forEach((item) => {
    counts.set(item, (counts.get(item) ?? 0) + 1)
  })

  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
}

function StatCard({ title, value, hint }: { title: string; value: string; hint: string }) {
  return (
    <Card>
      <CardHeader className="gap-1">
        <CardDescription>{title}</CardDescription>
        <CardTitle className="text-3xl">{value}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">{hint}</p>
      </CardContent>
    </Card>
  )
}

export function SessionListPage() {
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState<SessionListFilters>(DEFAULT_FILTERS)
  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
  } = useSessions(page, 20, filters)

  const sessions = useMemo(() => data?.items ?? [], [data?.items])
  const flaggedSessions = useMemo(
    () => sessions.filter((session) => session.risk_flag_count > 0),
    [sessions],
  )
  const sessionsWithProvenance = useMemo(
    () => sessions.filter((session) => session.provenance !== null),
    [sessions],
  )
  const inflectionSessions = useMemo(
    () => sessions.filter((session) => session.has_inflection),
    [sessions],
  )
  const sourceSummary = useMemo(
    () => summariseCounts(sessions.flatMap((session) => {
      const label = sourceLabel(session)
      return label ? [label] : []
    })).slice(0, 4),
    [sessions],
  )
  const parserSummary = useMemo(
    () => summariseCounts(sessions.map(parserLabel)).slice(0, 4),
    [sessions],
  )

  const activeFilterCount = [
    filters.flaggedOnly,
    filters.riskClass,
    filters.source,
    filters.sinceHours,
  ].filter(Boolean).length

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold">Session triage</h2>
          <p className="text-sm text-muted-foreground">Use the session home for daily review of flagged work, inflection, and provenance.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {activeFilterCount > 0 && <Badge variant="outline">{activeFilterCount} filter{activeFilterCount > 1 ? 's' : ''} active</Badge>}
          <Button
            size="sm"
            variant={filters.flaggedOnly ? 'default' : 'outline'}
            onClick={() => {
              setPage(1)
              setFilters((current) => ({ ...current, flaggedOnly: !current.flaggedOnly }))
            }}
          >
            {filters.flaggedOnly ? 'Flagged only on' : 'Flagged only off'}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setPage(1)
              setFilters(DEFAULT_FILTERS)
            }}
            disabled={activeFilterCount === 0}
          >
            Clear filters
          </Button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="Visible sessions"
          value={String(sessions.length)}
          hint={data ? `${data.total} total match the current query.` : 'Loading current slice.'}
        />
        <StatCard
          title="Flagged in slice"
          value={String(flaggedSessions.length)}
          hint="Flagged sessions visible on the current page."
        />
        <StatCard
          title="Inflection in slice"
          value={String(inflectionSessions.length)}
          hint="Sessions with a detected inflection point in the current slice."
        />
        <StatCard
          title="With provenance"
          value={String(sessionsWithProvenance.length)}
          hint="Sessions on this page that include ingest source metadata."
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Daily filters</CardTitle>
          <CardDescription>Query the server using the #42 triage filters instead of rebuilding state in the client.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3 xl:grid-cols-4">
          <div className="space-y-2">
            <div className="text-sm font-medium">Risk class</div>
            <Select
              value={filters.riskClass ?? 'all'}
              onValueChange={(value) => {
                setPage(1)
                setFilters((current) => ({
                  ...current,
                  riskClass: value === 'all' ? undefined : value,
                }))
              }}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="All risk classes" />
              </SelectTrigger>
              <SelectContent>
                {RISK_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <div className="text-sm font-medium">Source family</div>
            <Select
              value={filters.source ?? 'all'}
              onValueChange={(value) => {
                setPage(1)
                setFilters((current) => ({
                  ...current,
                  source: value === 'all' ? undefined : value,
                }))
              }}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="All sources" />
              </SelectTrigger>
              <SelectContent>
                {SOURCE_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <div className="text-sm font-medium">Time window</div>
            <Select
              value={filters.sinceHours ? String(filters.sinceHours) : 'all'}
              onValueChange={(value) => {
                setPage(1)
                setFilters((current) => ({
                  ...current,
                  sinceHours: value === 'all' ? undefined : Number(value),
                }))
              }}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="All time" />
              </SelectTrigger>
              <SelectContent>
                {WINDOW_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Recent flagged sessions</CardTitle>
            <CardDescription>The newest risky sessions visible on the current page.</CardDescription>
          </CardHeader>
          <CardContent>
            {flaggedSessions.length === 0 ? (
              <div className="text-sm text-muted-foreground">No flagged sessions are visible in the current slice.</div>
            ) : (
              <div className="space-y-3">
                {flaggedSessions.slice(0, 5).map((session) => (
                  <div key={session.id} className="flex flex-col gap-2 rounded-lg border p-3 md:flex-row md:items-center md:justify-between">
                    <div className="space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-sm">{session.id.slice(0, 8)}...</span>
                        <Badge variant="secondary">{session.agent_id ?? 'Unknown agent'}</Badge>
                        <Badge variant="destructive">{session.risk_flag_count} flagged</Badge>
                      </div>
                      <div className="text-sm text-muted-foreground">
                        {sourceDisplayLabel(session)} · {parserLabel(session)}
                      </div>
                    </div>
                    <div className="text-sm text-muted-foreground">
                      {new Date(session.started_at).toLocaleString()}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Provenance summary</CardTitle>
            <CardDescription>Keep source and parser context visible while triaging the day.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <div className="text-sm font-medium">Source mix</div>
              {sourceSummary.length === 0 ? (
                <div className="text-sm text-muted-foreground">No provenance is available for the current slice.</div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {sourceSummary.map(([label, count]) => (
                    <Badge key={label} variant="outline">{label} · {count}</Badge>
                  ))}
                </div>
              )}
            </div>

            <div className="space-y-2">
              <div className="text-sm font-medium">Parser versions</div>
              {parserSummary.length === 0 ? (
                <div className="text-sm text-muted-foreground">No parser versions are available.</div>
              ) : (
                <div className="space-y-2">
                  {parserSummary.map(([label, count]) => (
                    <div key={label} className="flex items-center justify-between text-sm">
                      <span className="truncate text-muted-foreground">{label}</span>
                      <span>{count}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="space-y-2">
              <div className="text-sm font-medium">Latest ingest</div>
              <div className="text-sm text-muted-foreground">
                {sessions.length > 0 ? latestIngestLabel(sessions) : 'No sessions loaded yet.'}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {isError && (
        <div className="border rounded-md p-4 bg-destructive/5 text-sm space-y-2">
          <p className="text-destructive font-medium">Failed to load sessions.</p>
          <p className="text-muted-foreground">{error instanceof Error ? error.message : 'Unexpected error.'}</p>
          <Button size="sm" variant="outline" onClick={() => refetch()}>Retry</Button>
        </div>
      )}

      {!isError && (
        <Card>
          <CardHeader>
            <CardTitle>Session queue</CardTitle>
            <CardDescription>The main review table stays in place, now with provenance alongside risk and inflection.</CardDescription>
          </CardHeader>
          <CardContent>
            <SessionList sessions={sessions} isLoading={isLoading} />
          </CardContent>
        </Card>
      )}

      {data && data.pages > 1 && (
        <div className="flex items-center gap-2 mt-4">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
          >
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {page} of {data.pages}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.min(data.pages, p + 1))}
            disabled={page >= data.pages}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  )
}
