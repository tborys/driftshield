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
            <Route path="/reports" element={<Navigate to="/sessions" replace />} />
            <Route path="*" element={<Navigate to="/sessions" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
