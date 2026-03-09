import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { SessionSummary, SessionDetail, PaginatedResponse, SessionListFilters } from '../types/session'
import type { GraphResponse } from '../types/graph'
import type { ValidationCreatePayload, ValidationRecord } from '../types/validation'

function buildSessionQuery(page: number, perPage: number, filters: SessionListFilters) {
  const params = new URLSearchParams({
    page: String(page),
    per_page: String(perPage),
  })

  if (filters.flaggedOnly) {
    params.set('flagged_only', 'true')
  }
  if (filters.riskClass) {
    params.set('risk_class', filters.riskClass)
  }
  if (filters.source) {
    params.set('source', filters.source)
  }
  if (filters.sinceHours) {
    params.set('since_hours', String(filters.sinceHours))
  }

  return params.toString()
}

export function useSessions(page = 1, perPage = 20, filters: SessionListFilters = {}) {
  return useQuery({
    queryKey: ['sessions', page, perPage, filters],
    queryFn: () => apiFetch<PaginatedResponse<SessionSummary>>(
      `/api/sessions?${buildSessionQuery(page, perPage, filters)}`
    ),
  })
}

export function useSession(id: string) {
  return useQuery({
    queryKey: ['session', id],
    queryFn: () => apiFetch<SessionDetail>(`/api/sessions/${id}`),
    enabled: !!id,
  })
}

export function useSessionGraph(id: string) {
  return useQuery({
    queryKey: ['session-graph', id],
    queryFn: () => apiFetch<GraphResponse>(`/api/sessions/${id}/graph`),
    enabled: !!id,
  })
}

export function useSessionValidations(sessionId: string) {
  return useQuery({
    queryKey: ['session-validations', sessionId],
    queryFn: () => apiFetch<ValidationRecord[]>(`/api/sessions/${sessionId}/validations`),
    enabled: !!sessionId,
  })
}

export function useCreateSessionValidation(sessionId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ValidationCreatePayload) =>
      apiFetch<ValidationRecord>(`/api/sessions/${sessionId}/validations`, {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session-validations', sessionId] })
    },
  })
}
