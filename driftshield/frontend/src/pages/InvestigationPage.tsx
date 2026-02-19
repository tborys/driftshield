import { useParams, Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useSession, useSessionGraph } from '../api/sessions'
import { InvestigationView } from '../components/investigation/InvestigationView'

export function InvestigationPage() {
  const { id } = useParams<{ id: string }>()
  const { data: session } = useSession(id!)
  const { data: graph, isLoading, error } = useSessionGraph(id!)

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
            </>
          )}
        </div>
      </div>
      <InvestigationView graph={graph} />
    </div>
  )
}
