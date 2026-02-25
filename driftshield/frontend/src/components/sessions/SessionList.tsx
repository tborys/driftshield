import { useNavigate } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import type { SessionSummary } from '../../types/session'

interface SessionListProps {
  sessions: SessionSummary[]
  isLoading: boolean
}

export function SessionList({ sessions, isLoading }: SessionListProps) {
  const navigate = useNavigate()

  if (isLoading) {
    return <div className="p-4 text-muted-foreground">Loading sessions...</div>
  }

  if (sessions.length === 0) {
    return <div className="p-4 text-muted-foreground">No sessions found.</div>
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Session ID</TableHead>
          <TableHead>Agent</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Risk Flags</TableHead>
          <TableHead>Inflection</TableHead>
          <TableHead>Recurrence</TableHead>
          <TableHead>Started</TableHead>
          <TableHead className="text-right">Action</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sessions.map((session) => (
          <TableRow
            key={session.id}
            className="cursor-pointer hover:bg-muted/50"
            onClick={() => navigate(`/sessions/${session.id}`)}
          >
            <TableCell className="font-mono text-sm">
              {session.id.slice(0, 8)}...
            </TableCell>
            <TableCell>{session.agent_id || '\u2014'}</TableCell>
            <TableCell>
              <Badge variant={session.status === 'completed' ? 'default' : 'secondary'}>
                {session.status}
              </Badge>
            </TableCell>
            <TableCell>
              {session.risk_flag_count > 0 ? (
                <Badge variant="destructive">{session.risk_flag_count}</Badge>
              ) : (
                <span className="text-muted-foreground">0</span>
              )}
            </TableCell>
            <TableCell>
              {session.has_inflection ? (
                <Badge variant="outline">Detected</Badge>
              ) : (
                <span className="text-muted-foreground">{'\u2014'}</span>
              )}
            </TableCell>
            <TableCell>
              {session.recurrence_level ? (
                <div className="flex items-center gap-2">
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
                  {session.recurrence_probability && (
                    <span className="text-xs text-muted-foreground">{session.recurrence_probability}</span>
                  )}
                </div>
              ) : (
                <span className="text-muted-foreground">new/unknown</span>
              )}
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">
              {new Date(session.started_at).toLocaleString()}
            </TableCell>
            <TableCell className="text-right">
              <Button
                size="sm"
                variant="outline"
                onClick={(e) => {
                  e.stopPropagation()
                  navigate(`/sessions/${session.id}`)
                }}
              >
                Open
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
