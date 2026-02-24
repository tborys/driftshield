import { useState } from 'react'
import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button } from '@/components/ui/button'
import { useGraveyardSummary } from '../api/graveyard'

export function ReportsPage() {
  const { data, isLoading, isError } = useGraveyardSummary()
  const [copied, setCopied] = useState(false)

  const handleDownload = () => {
    if (!data) return
    const blob = new Blob([data.content_markdown], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'driftshield-graveyard-summary.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleCopy = async () => {
    if (!data) return
    await navigator.clipboard.writeText(data.content_markdown)
    setCopied(true)
    setTimeout(() => setCopied(false), 1200)
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">Reports</h2>
          <p className="text-sm text-muted-foreground">Read summaries in UI and export markdown when needed.</p>
        </div>
        <Link to="/sessions">
          <Button variant="outline" size="sm">Back to Sessions</Button>
        </Link>
      </div>

      {isLoading && <div className="text-muted-foreground">Loading graveyard summary...</div>}

      {isError && (
        <div className="border rounded p-4 text-sm text-muted-foreground">
          No graveyard summary report available yet. Run <span className="font-mono">driftshield report-graveyard</span> to generate one.
        </div>
      )}

      {data && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleCopy}>{copied ? 'Copied' : 'Copy markdown'}</Button>
            <Button size="sm" onClick={handleDownload}>Download markdown</Button>
            <span className="text-xs text-muted-foreground">Source: {data.path}</span>
          </div>
          <article className="border rounded p-4 text-sm leading-6 bg-background space-y-2">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.content_markdown}</ReactMarkdown>
          </article>
        </div>
      )}
    </div>
  )
}
