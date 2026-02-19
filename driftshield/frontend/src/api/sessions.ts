import { useQuery } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { SessionSummary, SessionDetail, PaginatedResponse } from '../types/session'
import type { GraphResponse } from '../types/graph'

export function useSessions(page = 1, perPage = 20) {
  return useQuery({
    queryKey: ['sessions', page, perPage],
    queryFn: () => apiFetch<PaginatedResponse<SessionSummary>>(
      `/api/sessions?page=${page}&per_page=${perPage}`
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
