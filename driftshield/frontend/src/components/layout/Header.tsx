import { NavLink } from 'react-router-dom'

export function Header() {
  return (
    <header className="border-b px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-6">
        <h1 className="text-lg font-semibold">DriftShield</h1>
        <nav className="flex items-center gap-4 text-sm">
          <NavLink to="/sessions" className={({ isActive }) => (isActive ? 'font-medium' : 'text-muted-foreground')}>
            Sessions
          </NavLink>
        </nav>
      </div>
      <span className="text-sm text-muted-foreground">AI Decision Forensics</span>
    </header>
  )
}
