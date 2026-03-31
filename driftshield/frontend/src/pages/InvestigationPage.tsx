import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useSession, useSessionGraph } from '../api/sessions'
import { useSessionReports } from '../api/reports'
import { InvestigationView } from '../components/investigation/InvestigationView'
import { ReportTrigger } from '../components/reports/ReportTrigger'
import { ReportPreview } from '../components/reports/ReportPreview'

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

      <div className="px-6 py-3 border-b">
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

      <InvestigationView graph={graph} />
      <ReportPreview
        reportId={previewReportId}
        open={previewReportId !== null}
        onClose={() => setPreviewReportId(null)}
      />
    </div>
  )
}
