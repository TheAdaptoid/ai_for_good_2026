import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth'

export function Layout() {
  const { user, logout } = useAuth()
  return (
    <div className="app">
      <header className="topbar">
        <NavLink to="/" className="brand">TPA Video Review</NavLink>
        <nav aria-label="Main">
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/participants">Participants</NavLink>
        </nav>
        <div className="topbar__user">
          <span className="muted">{user?.username}</span>
          <button type="button" onClick={() => void logout()}>Sign out</button>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
