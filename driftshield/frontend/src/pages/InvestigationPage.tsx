import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useSession, useSessionGraph } from '../api/sessions'
import { useSessionReports } from '../api/reports'
import { InvestigationView } from '../components/investigation/InvestigationView'
import { ReportTrigger } from '../components/reports/ReportTrigger'
import { ReportPreview } from '../components/reports/ReportPreview'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'

function labelFromValue(value: string | null | undefined) {
  if (!value) {
    return null
  }

  return value.replace(/[_-]/g, ' ')
}

function SignatureAndRecurrenceCard({
  loading,
  session,
}: {
  loading: boolean
  session: ReturnType<typeof useSession>['data']
}) {
  const signatureMatch = session?.signature_match ?? null
  const recurrenceStatus = session?.recurrence_status ?? null
  const matchedFamilies = signatureMatch?.matched_family_ids ?? []
  const matchStatus = signatureMatch?.status ?? null
  const recurrenceLabel = labelFromValue(recurrenceStatus?.status)
  const signatureLabel = labelFromValue(matchStatus)
  const hasSignatureData = signatureMatch !== null
  const hasRecurrenceData = recurrenceStatus !== null
  const showUnavailable = !loading && !hasSignatureData && !hasRecurrenceData
  const showUnmatched = !loading && hasSignatureData && matchStatus === 'unmatched'

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Signature and recurrence</CardTitle>
        <CardDescription>
          Phase 2a classification output from the backend, with explicit unavailable states.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {loading ? (
          <div className="text-muted-foreground">Loading classification summary...</div>
        ) : showUnavailable ? (
          <div className="rounded-md border bg-muted/30 p-3 text-muted-foreground">
            This session does not expose signature or recurrence data yet.
          </div>
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              <Badge variant={matchStatus === 'matched' ? 'destructive' : 'outline'}>
                Signature: {signatureLabel ?? 'unavailable'}
              </Badge>
              <Badge variant={recurrenceStatus?.status === 'recurring' ? 'destructive' : 'outline'}>
                Recurrence: {recurrenceLabel ?? 'unavailable'}
              </Badge>
              {signatureMatch?.match_count !== null && signatureMatch?.match_count !== undefined && (
                <Badge variant="outline">{signatureMatch.match_count} match{signatureMatch.match_count === 1 ? '' : 'es'}</Badge>
              )}
              {recurrenceStatus?.recurrence_count !== null && recurrenceStatus?.recurrence_count !== undefined && (
                <Badge variant="outline">{recurrenceStatus.recurrence_count} related run{recurrenceStatus.recurrence_count === 1 ? '' : 's'}</Badge>
              )}
            </div>

            {signatureMatch?.summary && <p>{signatureMatch.summary}</p>}
            {!signatureMatch?.summary && showUnmatched && (
              <p className="text-muted-foreground">No signature matches were returned for this session.</p>
            )}
            {recurrenceStatus?.summary && <p>{recurrenceStatus.summary}</p>}

            {matchedFamilies.length > 0 && (
              <div className="space-y-2">
                <div className="text-xs font-medium text-muted-foreground">Matched families</div>
                <div className="flex flex-wrap gap-2">
                  {matchedFamilies.map((familyId) => (
                    <Badge key={familyId} variant="secondary">{labelFromValue(familyId) ?? familyId}</Badge>
                  ))}
                </div>
              </div>
            )}

            {signatureMatch?.primary_family_id && (
              <div className="text-muted-foreground">
                Primary family: <span className="font-medium text-foreground">{labelFromValue(signatureMatch.primary_family_id)}</span>
              </div>
            )}

            {recurrenceStatus?.cluster_id && (
              <div className="text-muted-foreground">
                Cluster: <span className="font-mono text-foreground">{recurrenceStatus.cluster_id}</span>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

export function InvestigationPage() {
  const { id } = useParams<{ id: string }>()
  const {
    data: session,
    isLoading: sessionLoading,
  } = useSession(id!)
  const {
    data: graph,
    isLoading,
    error,
    refetch: refetchGraph,
  } = useSessionGraph(id!)
  const {
    data: reports,
    isLoading: reportsLoading,
    isError: reportsError,
    error: reportsLoadError,
    refetch: refetchReports,
  } = useSessionReports(id!)
  const [previewReportId, setPreviewReportId] = useState<string | null>(null)

  if (isLoading) {
    return <div className="p-6 text-muted-foreground">Loading graph...</div>
  }

  if (error || !graph) {
    return (
      <div className="p-6 space-y-3">
        <div className="text-destructive font-medium">Failed to load graph data.</div>
        <p className="text-sm text-muted-foreground">{error instanceof Error ? error.message : 'Unexpected error.'}</p>
        <Button size="sm" variant="outline" onClick={() => refetchGraph()}>Retry graph load</Button>
      </div>
    )
  }

  return (
    <div>
      <div className="px-6 py-3 border-b flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/sessions">
            <Button variant="ghost" size="sm">&larr; Sessions</Button>
          </Link>
          <span className="font-mono text-sm">{id?.slice(0, 8)}...</span>
          {sessionLoading ? (
            <Badge variant="outline">Loading session...</Badge>
          ) : session ? (
            <>
              <Badge variant="secondary">{session.agent_id ?? 'Unknown agent'}</Badge>
              <Badge variant="outline">{session.status}</Badge>
              <Badge variant={session.risk_flag_count > 0 ? 'destructive' : 'outline'}>
                {session.risk_flag_count} flagged
              </Badge>
              {session.has_inflection && <Badge variant="outline">Inflection detected</Badge>}
            </>
          ) : (
            <Badge variant="outline">Session metadata unavailable</Badge>
          )}
        </div>
        <ReportTrigger sessionId={id!} onReportGenerated={setPreviewReportId} />
      </div>

      <div className="px-6 py-3 border-b grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-start">
        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm font-medium">Session reports</div>
            {reports && reports.length > 0 && (
              <Button variant="ghost" size="sm" onClick={() => setPreviewReportId(reports[0].id)}>
                Open latest
              </Button>
            )}
          </div>

        {reportsLoading && (
          <div className="text-sm text-muted-foreground">Loading report history...</div>
        )}

        {reportsError && (
          <div className="border rounded-md p-3 bg-destructive/5 text-sm space-y-2">
            <p className="text-destructive font-medium">Could not load report history.</p>
            <p className="text-muted-foreground">{reportsLoadError instanceof Error ? reportsLoadError.message : 'Unexpected error.'}</p>
            <Button size="sm" variant="outline" onClick={() => refetchReports()}>Retry</Button>
          </div>
        )}

        {!reportsLoading && !reportsError && (!reports || reports.length === 0) ? (
          <div className="text-sm text-muted-foreground">No reports yet. Generate one to review it in-app or export markdown.</div>
        ) : null}

        {!reportsLoading && !reportsError && reports && reports.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs text-muted-foreground">{reports.length} report{reports.length > 1 ? 's' : ''} available</div>
            <div className="flex flex-wrap gap-2">
              {reports.map((report) => (
                <Button key={report.id} variant="outline" size="sm" onClick={() => setPreviewReportId(report.id)}>
                  {report.report_type} · {new Date(report.generated_at).toLocaleString()}
                </Button>
              ))}
            </div>
          </div>
        )}
        </div>

        <SignatureAndRecurrenceCard loading={sessionLoading} session={session} />
      </div>

      <InvestigationView graph={graph} />
      <ReportPreview
        reportId={previewReportId}
        open={previewReportId !== null}
        onClose={() => setPreviewReportId(null)}
      />
    </div>
  )
}
