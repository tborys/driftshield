import { useQuery } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { GraveyardSummary } from '../types/session'

export function useGraveyardSummary() {
  return useQuery({
    queryKey: ['graveyard-summary'],
    queryFn: () => apiFetch<GraveyardSummary>('/api/graveyard/summary'),
  })
}
