import { useQuery, useQueryClient } from '@tanstack/react-query'
import { auth, setCurrentOrg } from '../../api/client'

export const sessionKey = ['session'] as const

/** allauth's view of the browser session: signed in, or which step is pending. */
export function useSession() {
  return useQuery({
    queryKey: sessionKey,
    queryFn: () => auth('/auth/session'),
    staleTime: 60_000,
    retry: false,
  })
}

export function useSignOut() {
  const client = useQueryClient()
  return async () => {
    await auth('/auth/session', { method: 'DELETE' })
    setCurrentOrg(null)
    client.clear()
    window.location.assign('/sign-in')
  }
}

/** Only follow `next` to a path inside this app. */
export function safeNext(next: string | null) {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/inbox'
}
