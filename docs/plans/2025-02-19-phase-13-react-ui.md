# Phase 13: React UI Foundation + Investigation View — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a React frontend with session browser, interactive lineage graph visualisation, node inspector, analyst validation controls and report generation/preview.

**Architecture:** Single page application. React Router for navigation. TanStack Query for server state. React Flow for graph rendering. shadcn/ui for components. API client talks to FastAPI backend.

**Tech Stack:** React 18, TypeScript, Vite, React Flow, shadcn/ui, Radix, Tailwind CSS, TanStack Query, React Router

**Design doc:** `docs/plans/2025-02-19-phases-10-14-design.md` (Phase 13 section)

**Prerequisite:** Phase 11 complete (API endpoints available)

---

## Task 13.1: Project Scaffolding

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/postcss.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/index.css`

**Step 1: Initialise the project**

```bash
cd .worktrees/driftshield-v1/driftshield
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```

**Step 2: Install core dependencies**

```bash
cd .worktrees/driftshield-v1/driftshield/frontend
npm install @tanstack/react-query react-router-dom @xyflow/react tailwindcss @tailwindcss/vite
npm install -D @types/react @types/react-dom typescript
```

**Step 3: Configure Tailwind**

`frontend/tailwind.config.ts`:
```typescript
import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: { extend: {} },
  plugins: [],
} satisfies Config
```

`frontend/src/index.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

**Step 4: Configure Vite proxy for API**

`frontend/vite.config.ts`:
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
})
```

**Step 5: Create minimal App**

`frontend/src/App.tsx`:
```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Routes, Route } from 'react-router-dom'

const queryClient = new QueryClient()

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<div>DriftShield</div>} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
```

**Step 6: Verify it runs**

```bash
cd .worktrees/driftshield-v1/driftshield/frontend
npm run dev
# Should open on http://localhost:5173 and show "DriftShield"
```

**Step 7: Commit**

```bash
cd .worktrees/driftshield-v1/driftshield
git add frontend/
git commit -m "feat(ui): scaffold React project with Vite, Tailwind, TanStack Query"
```

---

## Task 13.2: Install shadcn/ui

**Step 1: Initialise shadcn/ui**

```bash
cd .worktrees/driftshield-v1/driftshield/frontend
npx shadcn@latest init
```

Follow prompts: TypeScript, default style, CSS variables for theming.

**Step 2: Add initial components**

```bash
npx shadcn@latest add button table badge card dialog tabs separator input select
```

**Step 3: Verify build**

```bash
npm run build
```

Expected: Build succeeds with no errors.

**Step 4: Commit**

```bash
cd .worktrees/driftshield-v1/driftshield
git add frontend/
git commit -m "feat(ui): add shadcn/ui component library"
```

---

## Task 13.3: TypeScript Types and API Client

**Files:**
- Create: `frontend/src/types/session.ts`
- Create: `frontend/src/types/graph.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/sessions.ts`
- Create: `frontend/src/api/reports.ts`

**Step 1: Define TypeScript types**

```typescript
// frontend/src/types/session.ts
export interface SessionSummary {
  id: string
  agent_id: string | null
  external_id: string | null
  status: string
  started_at: string
  ended_at: string | null
  risk_flag_count: number
  has_inflection: boolean
}

export interface SessionDetail extends SessionSummary {
  total_events: number
  flagged_events: number
  risk_summary: Record<string, number>
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  per_page: number
  pages: number
}

export interface ReportSummary {
  id: string
  report_type: string
  generated_at: string
  generated_by: string | null
}

export interface ReportDetail {
  id: string
  session_id: string
  report_type: string
  generated_at: string
  content_markdown: string
  content_json: Record<string, unknown>
  generated_by: string | null
}
```

```typescript
// frontend/src/types/graph.ts
export interface GraphNode {
  id: string
  event_type: string
  action: string | null
  sequence_num: number
  risk_flags: string[]
  is_inflection: boolean
  inputs: Record<string, unknown> | null
  outputs: Record<string, unknown> | null
  metadata: Record<string, unknown> | null
  parent_node_id: string | null
}

export interface GraphEdge {
  source: string
  target: string
}

export interface GraphResponse {
  session_id: string
  nodes: GraphNode[]
  edges: GraphEdge[]
}
```

**Step 2: Create API client**

```typescript
// frontend/src/api/client.ts
const API_KEY = import.meta.env.VITE_API_KEY || ''

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      'X-API-Key': API_KEY,
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  return response.json()
}
```

```typescript
// frontend/src/api/sessions.ts
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
```

```typescript
// frontend/src/api/reports.ts
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
```

**Step 3: Verify build**

```bash
cd .worktrees/driftshield-v1/driftshield/frontend
npm run build
```

Expected: Build succeeds.

**Step 4: Commit**

```bash
cd .worktrees/driftshield-v1/driftshield
git add frontend/src/types/ frontend/src/api/
git commit -m "feat(ui): add TypeScript types and API client with TanStack Query hooks"
```

---

## Task 13.4: App Shell and Routing

**Files:**
- Create: `frontend/src/components/layout/AppShell.tsx`
- Create: `frontend/src/components/layout/Header.tsx`
- Create: `frontend/src/pages/SessionListPage.tsx`
- Create: `frontend/src/pages/InvestigationPage.tsx`
- Modify: `frontend/src/App.tsx`

**Step 1: Create layout components**

```tsx
// frontend/src/components/layout/Header.tsx
export function Header() {
  return (
    <header className="border-b px-6 py-3 flex items-center justify-between">
      <h1 className="text-lg font-semibold">DriftShield</h1>
      <span className="text-sm text-muted-foreground">AI Decision Forensics</span>
    </header>
  )
}
```

```tsx
// frontend/src/components/layout/AppShell.tsx
import { Outlet } from 'react-router-dom'
import { Header } from './Header'

export function AppShell() {
  return (
    <div className="min-h-screen flex flex-col">
      <Header />
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}
```

**Step 2: Create page stubs**

```tsx
// frontend/src/pages/SessionListPage.tsx
export function SessionListPage() {
  return (
    <div className="p-6">
      <h2 className="text-xl font-semibold mb-4">Sessions</h2>
      <p className="text-muted-foreground">Session list will go here.</p>
    </div>
  )
}
```

```tsx
// frontend/src/pages/InvestigationPage.tsx
import { useParams } from 'react-router-dom'

export function InvestigationPage() {
  const { id } = useParams<{ id: string }>()
  return (
    <div className="p-6">
      <h2 className="text-xl font-semibold mb-4">Investigation: {id}</h2>
      <p className="text-muted-foreground">Investigation view will go here.</p>
    </div>
  )
}
```

**Step 3: Wire up routing**

```tsx
// frontend/src/App.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { SessionListPage } from './pages/SessionListPage'
import { InvestigationPage } from './pages/InvestigationPage'

const queryClient = new QueryClient()

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<Navigate to="/sessions" replace />} />
            <Route path="/sessions" element={<SessionListPage />} />
            <Route path="/sessions/:id" element={<InvestigationPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
```

**Step 4: Verify**

```bash
cd .worktrees/driftshield-v1/driftshield/frontend
npm run build
```

**Step 5: Commit**

```bash
cd .worktrees/driftshield-v1/driftshield
git add frontend/src/
git commit -m "feat(ui): add app shell, routing, page stubs"
```

---

## Task 13.5: Session List Component

**Files:**
- Create: `frontend/src/components/sessions/SessionList.tsx`
- Create: `frontend/src/components/sessions/SessionFilters.tsx`
- Modify: `frontend/src/pages/SessionListPage.tsx`

**Step 1: Build SessionList component**

```tsx
// frontend/src/components/sessions/SessionList.tsx
import { useNavigate } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
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
          <TableHead>Started</TableHead>
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
            <TableCell>{session.agent_id || '—'}</TableCell>
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
                <span className="text-muted-foreground">—</span>
              )}
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">
              {new Date(session.started_at).toLocaleString()}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
```

**Step 2: Wire into page**

```tsx
// frontend/src/pages/SessionListPage.tsx
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
```

**Step 3: Verify build**

```bash
cd .worktrees/driftshield-v1/driftshield/frontend && npm run build
```

**Step 4: Commit**

```bash
cd .worktrees/driftshield-v1/driftshield
git add frontend/src/
git commit -m "feat(ui): add session list with pagination"
```

---

## Task 13.6: Lineage Graph Component

**Files:**
- Create: `frontend/src/components/investigation/LineageGraph.tsx`
- Create: `frontend/src/components/investigation/GraphNode.tsx`
- Create: `frontend/src/components/investigation/GraphEdge.tsx`

**Step 1: Create custom graph node**

```tsx
// frontend/src/components/investigation/GraphNode.tsx
import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { Badge } from '@/components/ui/badge'

export interface GraphNodeData {
  label: string
  eventType: string
  action: string | null
  riskFlags: string[]
  isInflection: boolean
}

export const GraphNodeComponent = memo(({ data, selected }: NodeProps) => {
  const nodeData = data as unknown as GraphNodeData
  return (
    <div
      className={`
        px-3 py-2 rounded-md border bg-background text-sm min-w-[160px]
        ${nodeData.isInflection ? 'border-orange-500 ring-2 ring-orange-200' : 'border-border'}
        ${selected ? 'ring-2 ring-primary' : ''}
        ${nodeData.riskFlags.length > 0 ? 'border-red-300' : ''}
      `}
    >
      <Handle type="target" position={Position.Top} className="!bg-muted-foreground" />
      <div className="flex items-center gap-1 mb-1">
        <Badge variant="secondary" className="text-xs">{nodeData.eventType}</Badge>
        {nodeData.isInflection && <Badge variant="outline" className="text-xs border-orange-500">inflection</Badge>}
      </div>
      <div className="font-medium truncate">{nodeData.action || '—'}</div>
      {nodeData.riskFlags.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {nodeData.riskFlags.map((flag) => (
            <Badge key={flag} variant="destructive" className="text-xs">{flag}</Badge>
          ))}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-muted-foreground" />
    </div>
  )
})

GraphNodeComponent.displayName = 'GraphNodeComponent'
```

**Step 2: Create lineage graph wrapper**

```tsx
// frontend/src/components/investigation/LineageGraph.tsx
import { useCallback, useMemo } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap,
  useNodesState, useEdgesState,
  type Node, type Edge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { GraphNodeComponent, type GraphNodeData } from './GraphNode'
import type { GraphResponse } from '../../types/graph'

interface LineageGraphProps {
  graph: GraphResponse
  onNodeSelect: (nodeId: string | null) => void
  selectedNodeId: string | null
}

const nodeTypes = { custom: GraphNodeComponent }

export function LineageGraph({ graph, onNodeSelect, selectedNodeId }: LineageGraphProps) {
  const initialNodes: Node[] = useMemo(
    () =>
      graph.nodes.map((node, index) => ({
        id: node.id,
        type: 'custom',
        position: { x: 250, y: index * 120 },
        data: {
          label: node.action || node.event_type,
          eventType: node.event_type,
          action: node.action,
          riskFlags: node.risk_flags,
          isInflection: node.is_inflection,
        } satisfies GraphNodeData,
        selected: node.id === selectedNodeId,
      })),
    [graph.nodes, selectedNodeId],
  )

  const initialEdges: Edge[] = useMemo(
    () =>
      graph.edges.map((edge, index) => ({
        id: `e-${index}`,
        source: edge.source,
        target: edge.target,
        animated: false,
      })),
    [graph.edges],
  )

  const [nodes, , onNodesChange] = useNodesState(initialNodes)
  const [edges, , onEdgesChange] = useEdgesState(initialEdges)

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeSelect(node.id)
    },
    [onNodeSelect],
  )

  const onPaneClick = useCallback(() => {
    onNodeSelect(null)
  }, [onNodeSelect])

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  )
}
```

**Step 3: Verify build**

```bash
cd .worktrees/driftshield-v1/driftshield/frontend && npm run build
```

**Step 4: Commit**

```bash
cd .worktrees/driftshield-v1/driftshield
git add frontend/src/components/investigation/
git commit -m "feat(ui): add lineage graph component with React Flow"
```

---

## Task 13.7: Node Inspector Component

**Files:**
- Create: `frontend/src/components/investigation/NodeInspector.tsx`
- Create: `frontend/src/components/investigation/RiskFlagBadge.tsx`

**Step 1: Create risk flag badge**

```tsx
// frontend/src/components/investigation/RiskFlagBadge.tsx
import { Badge } from '@/components/ui/badge'

const FLAG_DESCRIPTIONS: Record<string, string> = {
  assumption_mutation: 'An assumption was changed or contradicted during the decision path.',
  policy_divergence: 'The agent deviated from an established policy or rule.',
  constraint_violation: 'A hard constraint was breached.',
  context_contamination: 'Values from one context were misapplied to another.',
  coverage_gap: 'The output references fewer items than the input provided.',
}

interface RiskFlagBadgeProps {
  flag: string
  expanded?: boolean
}

export function RiskFlagBadge({ flag, expanded = false }: RiskFlagBadgeProps) {
  return (
    <div>
      <Badge variant="destructive">{flag.replace(/_/g, ' ')}</Badge>
      {expanded && (
        <p className="text-sm text-muted-foreground mt-1">
          {FLAG_DESCRIPTIONS[flag] || 'Unknown risk flag.'}
        </p>
      )}
    </div>
  )
}
```

**Step 2: Create node inspector**

```tsx
// frontend/src/components/investigation/NodeInspector.tsx
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { RiskFlagBadge } from './RiskFlagBadge'
import type { GraphNode } from '../../types/graph'

interface NodeInspectorProps {
  node: GraphNode | null
}

export function NodeInspector({ node }: NodeInspectorProps) {
  if (!node) {
    return (
      <div className="p-4 text-muted-foreground text-sm">
        Select a node in the graph to inspect it.
      </div>
    )
  }

  return (
    <div className="p-4 space-y-4 overflow-y-auto">
      <div>
        <h3 className="font-semibold text-lg">{node.action || 'Unknown action'}</h3>
        <div className="flex items-center gap-2 mt-1">
          <Badge variant="secondary">{node.event_type}</Badge>
          <span className="text-sm text-muted-foreground">#{node.sequence_num}</span>
          {node.is_inflection && (
            <Badge variant="outline" className="border-orange-500 text-orange-600">
              Inflection Node
            </Badge>
          )}
        </div>
      </div>

      <Separator />

      {node.risk_flags.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Risk Flags</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {node.risk_flags.map((flag) => (
              <RiskFlagBadge key={flag} flag={flag} expanded />
            ))}
          </CardContent>
        </Card>
      )}

      {node.inputs && Object.keys(node.inputs).length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Inputs</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted p-2 rounded overflow-x-auto">
              {JSON.stringify(node.inputs, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}

      {node.outputs && Object.keys(node.outputs).length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Outputs</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted p-2 rounded overflow-x-auto">
              {JSON.stringify(node.outputs, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}

      {node.metadata && Object.keys(node.metadata).length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Metadata</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted p-2 rounded overflow-x-auto">
              {JSON.stringify(node.metadata, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
```

**Step 3: Verify build**

```bash
cd .worktrees/driftshield-v1/driftshield/frontend && npm run build
```

**Step 4: Commit**

```bash
cd .worktrees/driftshield-v1/driftshield
git add frontend/src/components/investigation/
git commit -m "feat(ui): add node inspector and risk flag badge components"
```

---

## Task 13.8: Investigation View (Wire It Together)

**Files:**
- Create: `frontend/src/components/investigation/InvestigationView.tsx`
- Modify: `frontend/src/pages/InvestigationPage.tsx`

**Step 1: Create investigation view**

```tsx
// frontend/src/components/investigation/InvestigationView.tsx
import { useState, useMemo } from 'react'
import { LineageGraph } from './LineageGraph'
import { NodeInspector } from './NodeInspector'
import type { GraphResponse, GraphNode } from '../../types/graph'

interface InvestigationViewProps {
  graph: GraphResponse
}

export function InvestigationView({ graph }: InvestigationViewProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)

  const selectedNode: GraphNode | null = useMemo(
    () => graph.nodes.find((n) => n.id === selectedNodeId) ?? null,
    [graph.nodes, selectedNodeId],
  )

  return (
    <div className="flex h-[calc(100vh-57px)]">
      <div className="flex-1">
        <LineageGraph
          graph={graph}
          onNodeSelect={setSelectedNodeId}
          selectedNodeId={selectedNodeId}
        />
      </div>
      <div className="w-[400px] border-l overflow-y-auto">
        <NodeInspector node={selectedNode} />
      </div>
    </div>
  )
}
```

**Step 2: Wire into investigation page**

```tsx
// frontend/src/pages/InvestigationPage.tsx
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
```

**Step 3: Verify build**

```bash
cd .worktrees/driftshield-v1/driftshield/frontend && npm run build
```

**Step 4: Commit**

```bash
cd .worktrees/driftshield-v1/driftshield
git add frontend/src/
git commit -m "feat(ui): add investigation view wiring graph and inspector"
```

---

## Task 13.9: Validation Controls

**Files:**
- Create: `frontend/src/components/validation/ValidationControls.tsx`
- Modify: `frontend/src/components/investigation/NodeInspector.tsx`

**Step 1: Create validation controls**

```tsx
// frontend/src/components/validation/ValidationControls.tsx
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import type { GraphNode } from '../../types/graph'

interface ValidationControlsProps {
  node: GraphNode
}

export function ValidationControls({ node }: ValidationControlsProps) {
  const [inflectionValidation, setInflectionValidation] = useState<'confirmed' | 'rejected' | null>(null)
  const [riskValidations, setRiskValidations] = useState<Record<string, 'validated' | 'disputed' | 'false_positive'>>({})

  const handleInflectionValidation = (decision: 'confirmed' | 'rejected') => {
    setInflectionValidation(decision)
    // TODO: POST to API when validation endpoints exist
  }

  const handleRiskValidation = (flag: string, decision: 'validated' | 'disputed' | 'false_positive') => {
    setRiskValidations(prev => ({ ...prev, [flag]: decision }))
    // TODO: POST to API when validation endpoints exist
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Analyst Validation</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {node.is_inflection && (
          <div>
            <p className="text-sm font-medium mb-2">Inflection Node</p>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant={inflectionValidation === 'confirmed' ? 'default' : 'outline'}
                onClick={() => handleInflectionValidation('confirmed')}
              >
                Confirm
              </Button>
              <Button
                size="sm"
                variant={inflectionValidation === 'rejected' ? 'destructive' : 'outline'}
                onClick={() => handleInflectionValidation('rejected')}
              >
                Reject
              </Button>
            </div>
            {inflectionValidation && (
              <p className="text-xs text-muted-foreground mt-1">
                {inflectionValidation === 'confirmed' ? 'Confirmed as inflection point.' : 'Rejected as inflection point.'}
              </p>
            )}
          </div>
        )}

        {node.risk_flags.length > 0 && (
          <>
            {node.is_inflection && <Separator />}
            <div>
              <p className="text-sm font-medium mb-2">Risk Flags</p>
              {node.risk_flags.map((flag) => (
                <div key={flag} className="mb-2">
                  <p className="text-xs font-medium mb-1">{flag.replace(/_/g, ' ')}</p>
                  <div className="flex gap-1">
                    <Button
                      size="sm" variant={riskValidations[flag] === 'validated' ? 'default' : 'outline'}
                      className="text-xs h-7"
                      onClick={() => handleRiskValidation(flag, 'validated')}
                    >
                      Validate
                    </Button>
                    <Button
                      size="sm" variant={riskValidations[flag] === 'disputed' ? 'secondary' : 'outline'}
                      className="text-xs h-7"
                      onClick={() => handleRiskValidation(flag, 'disputed')}
                    >
                      Dispute
                    </Button>
                    <Button
                      size="sm" variant={riskValidations[flag] === 'false_positive' ? 'destructive' : 'outline'}
                      className="text-xs h-7"
                      onClick={() => handleRiskValidation(flag, 'false_positive')}
                    >
                      False positive
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {!node.is_inflection && node.risk_flags.length === 0 && (
          <p className="text-sm text-muted-foreground">No validation actions available for this node.</p>
        )}
      </CardContent>
    </Card>
  )
}
```

**Step 2: Add ValidationControls to NodeInspector**

Add to the bottom of `NodeInspector`, after the metadata card:

```tsx
import { ValidationControls } from '../validation/ValidationControls'

// Inside NodeInspector component, after existing cards:
<Separator />
<ValidationControls node={node} />
```

**Step 3: Verify build**

```bash
cd .worktrees/driftshield-v1/driftshield/frontend && npm run build
```

**Step 4: Commit**

```bash
cd .worktrees/driftshield-v1/driftshield
git add frontend/src/
git commit -m "feat(ui): add analyst validation controls for inflection and risk flags"
```

---

## Task 13.10: Report Generation and Preview

**Files:**
- Create: `frontend/src/components/reports/ReportTrigger.tsx`
- Create: `frontend/src/components/reports/ReportPreview.tsx`
- Modify: `frontend/src/pages/InvestigationPage.tsx`

**Step 1: Create report trigger**

```tsx
// frontend/src/components/reports/ReportTrigger.tsx
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
  const generateReport = useGenerateReport(sessionId)

  const handleGenerate = async () => {
    const result = await generateReport.mutateAsync(reportType)
    onReportGenerated(result.id)
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
    </div>
  )
}
```

**Step 2: Create report preview**

```tsx
// frontend/src/components/reports/ReportPreview.tsx
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import { useReport } from '../../api/reports'

interface ReportPreviewProps {
  reportId: string | null
  open: boolean
  onClose: () => void
}

export function ReportPreview({ reportId, open, onClose }: ReportPreviewProps) {
  const { data: report, isLoading } = useReport(reportId || '')

  const handleDownload = () => {
    if (!report) return
    const blob = new Blob([report.content_markdown], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `driftshield-report-${report.session_id.slice(0, 8)}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Forensic Analysis Report</DialogTitle>
        </DialogHeader>
        {isLoading ? (
          <div className="text-muted-foreground">Loading report...</div>
        ) : report ? (
          <pre className="text-sm whitespace-pre-wrap font-mono bg-muted p-4 rounded">
            {report.content_markdown}
          </pre>
        ) : (
          <div className="text-destructive">Failed to load report.</div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Close</Button>
          <Button onClick={handleDownload} disabled={!report}>Download Markdown</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

**Step 3: Wire into investigation page header**

Add to `InvestigationPage.tsx`:

```tsx
import { useState } from 'react'
import { ReportTrigger } from '../components/reports/ReportTrigger'
import { ReportPreview } from '../components/reports/ReportPreview'

// Inside InvestigationPage component:
const [previewReportId, setPreviewReportId] = useState<string | null>(null)

// In the header bar, after badges:
<ReportTrigger sessionId={id!} onReportGenerated={setPreviewReportId} />

// Before closing </div>:
<ReportPreview
  reportId={previewReportId}
  open={previewReportId !== null}
  onClose={() => setPreviewReportId(null)}
/>
```

**Step 4: Verify build**

```bash
cd .worktrees/driftshield-v1/driftshield/frontend && npm run build
```

**Step 5: Commit**

```bash
cd .worktrees/driftshield-v1/driftshield
git add frontend/src/
git commit -m "feat(ui): add report generation trigger and Markdown preview dialog"
```

---

## Task 13.11: Auto-layout with dagre

**Files:**
- Modify: `frontend/src/components/investigation/LineageGraph.tsx`

**Step 1: Install dagre**

```bash
cd .worktrees/driftshield-v1/driftshield/frontend
npm install @dagrejs/dagre
```

**Step 2: Add layout function**

Update `LineageGraph.tsx` to use dagre for automatic DAG layout instead of stacking nodes vertically:

```typescript
import Dagre from '@dagrejs/dagre'

function layoutNodes(graph: GraphResponse): { nodes: Node[]; edges: Edge[] } {
  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'TB', nodesep: 50, ranksep: 80 })

  graph.nodes.forEach((node) => {
    g.setNode(node.id, { width: 200, height: 80 })
  })

  graph.edges.forEach((edge) => {
    g.setEdge(edge.source, edge.target)
  })

  Dagre.layout(g)

  const nodes: Node[] = graph.nodes.map((node) => {
    const pos = g.node(node.id)
    return {
      id: node.id,
      type: 'custom',
      position: { x: pos.x - 100, y: pos.y - 40 },
      data: {
        label: node.action || node.event_type,
        eventType: node.event_type,
        action: node.action,
        riskFlags: node.risk_flags,
        isInflection: node.is_inflection,
      } satisfies GraphNodeData,
    }
  })

  const edges: Edge[] = graph.edges.map((edge, index) => ({
    id: `e-${index}`,
    source: edge.source,
    target: edge.target,
  }))

  return { nodes, edges }
}
```

Replace the `useMemo` calls for `initialNodes` and `initialEdges` with a single call to `layoutNodes`.

**Step 3: Verify build**

```bash
cd .worktrees/driftshield-v1/driftshield/frontend && npm run build
```

**Step 4: Commit**

```bash
cd .worktrees/driftshield-v1/driftshield
git add frontend/
git commit -m "feat(ui): add dagre auto-layout for lineage graph"
```
