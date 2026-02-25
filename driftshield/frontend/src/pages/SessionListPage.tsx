import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { SessionList } from '../components/sessions/SessionList'
import { useSessions } from '../api/sessions'

export function SessionListPage() {
  const [page, setPage] = useState(1)
  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
  } = useSessions(page)

  return (
    <div className="p-6 space-y-4">
      <div>
        <h2 className="text-xl font-semibold">Sessions</h2>
        <p className="text-sm text-muted-foreground">Review incidents, inspect inflection points and open reports.</p>
      </div>

      {isError && (
        <div className="border rounded-md p-4 bg-destructive/5 text-sm space-y-2">
          <p className="text-destructive font-medium">Failed to load sessions.</p>
          <p className="text-muted-foreground">{error instanceof Error ? error.message : 'Unexpected error.'}</p>
          <Button size="sm" variant="outline" onClick={() => refetch()}>Retry</Button>
        </div>
      )}

      {!isError && (
        <SessionList sessions={data?.items ?? []} isLoading={isLoading} />
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
