import { useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router'
import { Logo } from '../design/Logo'
import { Menu, MenuItem, MenuLabel, MenuSeparator } from '../design/overlays'
import { useSignOut } from '../features/auth/session'
import { useOrg } from './Gate'
import { useHotkeys } from './hotkeys'
import { ShortcutOverlay } from './ShortcutOverlay'
import './shell.css'

const ROLE_WORD: Record<string, string> = {
  owner: 'Owner',
  admin: 'Admin',
  qa_lead: 'QA lead',
  qa_engineer: 'QA engineer',
  developer: 'Developer',
  viewer: 'Viewer',
}

export function AppShell() {
  const navigate = useNavigate()
  const [help, setHelp] = useState(false)
  useHotkeys({
    '?': () => setHelp(true),
    'g i': () => navigate('/inbox'),
    'g p': () => navigate('/projects'),
    'g s': () => navigate('/settings'),
  })

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/inbox" className="topbar-logo" aria-label="Greenlit, go to Inbox">
            <Logo width={96} />
          </Link>
          <nav className="topnav" aria-label="Main">
            <NavLink to="/inbox">Inbox</NavLink>
            <NavLink to="/projects">Projects</NavLink>
            <NavLink to="/settings">Settings</NavLink>
          </nav>
          <div className="topbar-end">
            <button type="button" className="kbd-hint" onClick={() => setHelp(true)} aria-label="Keyboard shortcuts">
              <kbd>?</kbd>
            </button>
            <OrgSwitcher />
            <UserMenu />
          </div>
        </div>
      </header>
      <main id="main" className="page" tabIndex={-1}>
        <Outlet />
      </main>
      <ShortcutOverlay open={help} onOpenChange={setHelp} />
    </div>
  )
}

function OrgSwitcher() {
  const { me, membership, switchOrg } = useOrg()
  const active = me.memberships.filter((m) => m.status === 'active')
  return (
    <Menu
      trigger={
        <button type="button" className="org-trigger" aria-label={`Organisation: ${membership.organisation.name}. Switch organisation`}>
          <span className="org-name">{membership.organisation.name}</span>
          <span className="org-role">{ROLE_WORD[membership.role] ?? membership.role}</span>
          <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
            <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      }
    >
      <MenuLabel>Organisations</MenuLabel>
      {active.map((m) => (
        <MenuItem key={m.organisation.id} onSelect={() => m.organisation.slug !== membership.organisation.slug && switchOrg(m.organisation.slug)}>
          <span className="menu-check" aria-hidden="true">
            {m.organisation.slug === membership.organisation.slug ? '✓' : ''}
          </span>
          <span style={{ flex: 1 }}>{m.organisation.name}</span>
          <span className="faint" style={{ fontSize: 12.5 }}>
            {ROLE_WORD[m.role] ?? m.role}
          </span>
        </MenuItem>
      ))}
    </Menu>
  )
}

function UserMenu() {
  const { me } = useOrg()
  const signOut = useSignOut()
  const navigate = useNavigate()
  const initials = (me.name || me.email)
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join('')
  return (
    <Menu
      trigger={
        <button type="button" className="avatar" aria-label={`Account: ${me.name || me.email}`}>
          {initials}
        </button>
      }
    >
      <MenuLabel>{me.email}</MenuLabel>
      <MenuItem onSelect={() => navigate('/settings')}>Settings</MenuItem>
      <MenuSeparator />
      <MenuItem onSelect={signOut}>Sign out</MenuItem>
    </Menu>
  )
}
