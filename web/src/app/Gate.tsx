import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'
import { getCurrentOrg, setCurrentOrg } from '../api/client'
import { useMe, type Me } from '../api/queries'
import { ErrorState } from '../design/states'
import { useSession } from '../features/auth/session'

type Membership = Me['memberships'][number]

type Ctx = { me: Me; membership: Membership; switchOrg: (slug: string) => void }
const OrgContext = createContext<Ctx | null>(null)

export function useOrg() {
  const ctx = useContext(OrgContext)
  if (!ctx) throw new Error('useOrg outside the signed-in app')
  return ctx
}

function Splash() {
  return <div className="splash" aria-busy="true" aria-label="Loading Greenlit" />
}

/**
 * Signed in → has an organisation → enrolled in two-step verification if the role needs it.
 * Each missing step sends the person to the screen that fixes it.
 */
export function Gate({ children }: { children: ReactNode }) {
  const location = useLocation()
  const session = useSession()
  const signedIn = session.data?.authenticated === true
  const me = useMe(signedIn)
  const client = useQueryClient()
  const navigate = useNavigate()
  const [orgVersion, setOrgVersion] = useState(0)

  // Switching drops every cached record of the old organisation before anything renders.
  const switchOrg = useCallback(
    (slug: string) => {
      setCurrentOrg(slug)
      client.removeQueries({ queryKey: ['org'] })
      setOrgVersion((v) => v + 1)
      navigate('/inbox')
    },
    [client, navigate],
  )

  const membership = useMemo(() => {
    const active = me.data?.memberships.filter((m) => m.status === 'active') ?? []
    if (!active.length) return null
    const chosen = active.find((m) => m.organisation.slug === getCurrentOrg()) ?? active[0]
    if (chosen.organisation.slug !== getCurrentOrg()) setCurrentOrg(chosen.organisation.slug)
    return chosen
    // eslint-disable-next-line react-hooks/exhaustive-deps -- orgVersion re-reads the stored choice
  }, [me.data, orgVersion])

  const here = location.pathname + location.search
  if (session.isPending) return <Splash />
  if (!signedIn) {
    if (session.data?.pending === 'mfa_authenticate') return <Navigate to={`/two-step?next=${encodeURIComponent(here)}`} replace />
    return <Navigate to={`/sign-in${here === '/' ? '' : `?next=${encodeURIComponent(here)}`}`} replace />
  }
  if (me.isPending) return <Splash />
  if (me.isError || !me.data) return <ErrorState message="Couldn't load your account." onRetry={() => me.refetch()} />
  if (!membership) return <Navigate to="/welcome" replace />
  if (membership.needs_mfa) return <Navigate to={`/two-step/setup?next=${encodeURIComponent(here)}`} replace />

  return <OrgContext.Provider value={{ me: me.data, membership, switchOrg }}>{children}</OrgContext.Provider>
}

/** For pages that need a session but no organisation yet (welcome, invite, two-step setup). */
export function SignedInOnly({ children }: { children: ReactNode }) {
  const location = useLocation()
  const session = useSession()
  if (session.isPending) return <Splash />
  if (!session.data?.authenticated) {
    return <Navigate to={`/sign-in?next=${encodeURIComponent(location.pathname)}`} replace />
  }
  return <>{children}</>
}
