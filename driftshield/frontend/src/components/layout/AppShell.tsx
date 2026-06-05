import { Outlet } from 'react-router-dom'
import { Header } from './Header'

export function AppShell() {
  return (
    <>
      <div className="ds-app-bg" aria-hidden="true" />
      <div className="ds-app-shell min-h-screen flex flex-col">
        <Header />
        <main className="flex-1">
          <Outlet />
        </main>
      </div>
    </>
  )
}
