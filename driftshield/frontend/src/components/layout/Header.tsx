import { NavLink } from 'react-router-dom'

export function Header() {
  return (
    <header className="ds-header px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-6">
        <NavLink to="/sessions" className="flex items-center" aria-label="DriftShield home">
          {/* DriftShield brand wordmark. */}
          <img src="/logo-text-white.png" alt="DriftShield" className="ds-nav-logo" width={172} height={43} />
        </NavLink>
        <nav className="flex items-center gap-4 text-sm">
          <NavLink
            to="/sessions"
            className={({ isActive }) =>
              isActive ? 'font-medium text-foreground' : 'text-muted-foreground hover:text-foreground transition-colors'
            }
          >
            Sessions
          </NavLink>
        </nav>
      </div>
      <span className="ds-eyebrow hidden sm:inline">AI Decision Forensics</span>
    </header>
  )
}
