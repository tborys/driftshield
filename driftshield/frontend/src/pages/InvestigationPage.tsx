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
  const { data: session } = useSession(id!)
  const { data: graph, isLoading, error } = useSessionGraph(id!)
  const { data: reports } = useSessionReports(id!)
  const [previewReportId, setPreviewReportId] = useState<string | null>(null)

  if (isLoading) {
    return <div className="p-6 text-muted-foreground">Loading graph...</div>
  }

  if (error || !graph) {
    return <div className="p-6 text-destructive">Failed to load graph data.</div>
  }

  return (
    <div>
      <div className="px-6 py-3 border-b flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/sessions">
            <Button variant="ghost" size="sm">&larr; Sessions</Button>
          </Link>
          <span className="font-mono text-sm">{id?.slice(0, 8)}...</span>
          {session && (
            <>
              <Badge variant="secondary">{session.agent_id}</Badge>
              <Badge variant="outline">{session.status}</Badge>
              {session.recurrence_level && (
                <Badge
                  variant={
                    session.recurrence_level === 'systemic'
                      ? 'destructive'
                      : session.recurrence_level === 'recurring'
                        ? 'secondary'
                        : 'outline'
                  }
                >
                  {session.recurrence_level}
                </Badge>
              )}
              {session.recurrence_probability && (
                <Badge variant="outline">{session.recurrence_probability} confidence</Badge>
              )}
            </>
          )}
        </div>
        <ReportTrigger sessionId={id!} onReportGenerated={setPreviewReportId} />
      </div>
      {session?.recurrence_level && (
        <div className="px-6 py-2 border-b text-sm text-muted-foreground">
          Recurrence insight: this pattern is currently classified as <span className="font-medium">{session.recurrence_level}</span>
          {session.recurrence_count ? ` (${session.recurrence_count} observed session${session.recurrence_count > 1 ? 's' : ''})` : ''}.
          {session.recurrence_probability ? ` Confidence: ${session.recurrence_probability}.` : ''}
        </div>
      )}

      <div className="px-6 py-3 border-b">
        <div className="flex items-center justify-between mb-2">
          <div className="text-sm font-medium">Session reports</div>
          {reports && reports.length > 0 && (
            <Button variant="ghost" size="sm" onClick={() => setPreviewReportId(reports[0].id)}>
              Open latest
            </Button>
          )}
        </div>
        {!reports || reports.length === 0 ? (
          <div className="text-sm text-muted-foreground">No reports yet. Generate one to review it in-app or export markdown.</div>
        ) : (
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
