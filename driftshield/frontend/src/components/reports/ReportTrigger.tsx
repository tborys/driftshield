import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { useGenerateReport } from '../../api/reports'

interface ReportTriggerProps {
  sessionId: string
  onReportGenerated: (reportId: string) => void
}

export function ReportTrigger({ sessionId, onReportGenerated }: ReportTriggerProps) {
  const [reportType, setReportType] = useState('full')
  const [lastGeneratedType, setLastGeneratedType] = useState<string | null>(null)
  const generateReport = useGenerateReport(sessionId)

  const handleGenerate = async () => {
    const result = await generateReport.mutateAsync(reportType)
    onReportGenerated(result.id)
    setLastGeneratedType(reportType)
  }

  return (
    <div className="flex items-center gap-2">
      <Select value={reportType} onValueChange={setReportType}>
        <SelectTrigger className="w-[140px] h-8">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="full">Full report</SelectItem>
          <SelectItem value="summary">Summary</SelectItem>
        </SelectContent>
      </Select>
      <Button
        size="sm"
        onClick={handleGenerate}
        disabled={generateReport.isPending}
      >
        {generateReport.isPending ? 'Generating...' : 'Generate Report'}
      </Button>
      {lastGeneratedType && !generateReport.isPending && (
        <span className="text-xs text-muted-foreground">
          {lastGeneratedType} report ready
        </span>
      )}
    </div>
  )
}
