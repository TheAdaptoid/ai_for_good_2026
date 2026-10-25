import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth'

export function Layout() {
  const { user, logout } = useAuth()
  return (
    <div className="app">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="sidebar">
        <NavLink to="/" className="brand">TPA Video Review</NavLink>
        <nav aria-label="Main">
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/review">Review</NavLink>
          <NavLink to="/participants">Participants</NavLink>
        </nav>
        <div className="sidebar__user">
          <span className="muted">{user?.username}</span>
          <button type="button" onClick={() => void logout()}>Sign out</button>
        </div>
      </header>
      <main id="main-content" className="content" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  )
}
