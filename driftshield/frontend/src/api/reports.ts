import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { ReportSummary, ReportDetail } from '../types/session'

export function useSessionReports(sessionId: string) {
  return useQuery({
    queryKey: ['session-reports', sessionId],
    queryFn: () => apiFetch<ReportSummary[]>(`/api/sessions/${sessionId}/reports`),
    enabled: !!sessionId,
  })
}

export function useReport(reportId: string) {
  return useQuery({
    queryKey: ['report', reportId],
    queryFn: () => apiFetch<ReportDetail>(`/api/reports/${reportId}`),
    enabled: !!reportId,
  })
}

export function useGenerateReport(sessionId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (reportType: string) =>
      apiFetch<{ id: string; report_type: string }>(`/api/sessions/${sessionId}/report`, {
        method: 'POST',
        body: JSON.stringify({ report_type: reportType }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session-reports', sessionId] })
    },
  })
}
