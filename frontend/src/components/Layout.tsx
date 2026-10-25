import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth'
import logo from '../assets/tpa-logo.png'
import forestLogo from '../assets/random-forest-logo.png'
import { Icon } from './Icon'

export function Layout() {
  const { user, logout } = useAuth()
  return (
    <div className="app">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="sidebar">
        <NavLink to="/" className="brand">
          <img className="brand__logo" src={logo} alt="The Performance Academy, Florida: dashboard" width={300} height={300} />
        </NavLink>
        <nav aria-label="Main">
          <NavLink to="/" end><Icon name="dashboard" />Dashboard</NavLink>
          <NavLink to="/review"><Icon name="review" />Review</NavLink>
          <NavLink to="/participants"><Icon name="participants" />Participants</NavLink>
          <NavLink to="/data"><Icon name="data" />Data view</NavLink>
          <NavLink to="/ingestion"><Icon name="ingest" />Data Ingestion</NavLink>
        </nav>
        <div className="sidebar__user">
          <span className="profile">
            <svg className="profile__avatar" viewBox="0 0 32 32" aria-hidden="true">
              <circle cx="16" cy="16" r="16" />
              <circle cx="16" cy="12.5" r="5.5" className="profile__figure" />
              <path d="M6.5 26.5a9.5 7.5 0 0 1 19 0" className="profile__figure" />
            </svg>
            <span className="profile__name">{user?.username}</span>
          </span>
          <button type="button" className="sign-out" onClick={() => void logout()}><Icon name="signOut" />Sign out</button>
        </div>
      </header>
      <main id="main-content" className="content" tabIndex={-1}>
        <Outlet />
        <footer className="site-footer">
          <img src={forestLogo} alt="" width={166} height={134} />
          <p>Product of Random Forest LLC <span aria-hidden="true">·</span> © 2026</p>
        </footer>
      </main>
    </div>
  )
}
