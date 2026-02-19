import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { SessionList } from '../components/sessions/SessionList'
import { useSessions } from '../api/sessions'

export function SessionListPage() {
  const [page, setPage] = useState(1)
  const { data, isLoading } = useSessions(page)

  return (
    <div className="p-6">
      <h2 className="text-xl font-semibold mb-4">Sessions</h2>
      <SessionList sessions={data?.items ?? []} isLoading={isLoading} />
      {data && data.pages > 1 && (
        <div className="flex items-center gap-2 mt-4">
          <Button
            variant="outline" size="sm"
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
          >
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {page} of {data.pages}
          </span>
          <Button
            variant="outline" size="sm"
            onClick={() => setPage(p => Math.min(data.pages, p + 1))}
            disabled={page >= data.pages}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  )
}
