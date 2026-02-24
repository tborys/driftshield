import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useReport } from '../../api/reports'

interface ReportPreviewProps {
  reportId: string | null
  open: boolean
  onClose: () => void
}

export function ReportPreview({ reportId, open, onClose }: ReportPreviewProps) {
  const { data: report, isLoading } = useReport(reportId || '')

  const handleDownload = () => {
    if (!report) return
    const blob = new Blob([report.content_markdown], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `driftshield-report-${report.session_id.slice(0, 8)}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Forensic Analysis Report</DialogTitle>
        </DialogHeader>
        {isLoading ? (
          <div className="text-muted-foreground">Loading report...</div>
        ) : report ? (
          <article className="text-sm leading-6 bg-muted p-4 rounded border space-y-2">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.content_markdown}</ReactMarkdown>
          </article>
        ) : (
          <div className="text-destructive">Failed to load report.</div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Close</Button>
          <Button onClick={handleDownload} disabled={!report}>Download Markdown</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
