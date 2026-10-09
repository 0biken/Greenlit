import { QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api, getCurrentOrg } from './client'
import type { Inbox, ProjectSummary, ReleaseDetail } from './planned'
import type { components } from './schema'

export type Me = components['schemas']['Me']
export type Project = components['schemas']['Project']
export type Member = components['schemas']['Member']

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // A 404 means "not yours or not there"; asking again will not change that.
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
      refetchOnWindowFocus: true,
    },
  },
})

// Keys include the organisation so switching never shows another organisation's data.
const org = () => getCurrentOrg() ?? '-'

export const keys = {
  me: ['me'] as const,
  projects: () => ['org', org(), 'projects'] as const,
  members: () => ['org', org(), 'members'] as const,
  inbox: (snoozed: boolean) => ['org', org(), 'inbox', snoozed] as const,
  summary: (key: string) => ['org', org(), 'project', key, 'summary'] as const,
  release: (key: string, version: string) => ['org', org(), 'project', key, 'release', version] as const,
}

export const useMe = (enabled = true) =>
  useQuery({ queryKey: keys.me, queryFn: () => api<Me>('/api/me/', { noOrg: true }), enabled })

export const useProjects = () => useQuery({ queryKey: keys.projects(), queryFn: () => api<Project[]>('/api/projects/') })

export const useMembers = () => useQuery({ queryKey: keys.members(), queryFn: () => api<Member[]>('/api/members/') })

export const useInbox = (snoozed = false) =>
  useQuery({
    queryKey: keys.inbox(snoozed),
    queryFn: () => api<Inbox>(`/api/inbox/${snoozed ? '?snoozed=1' : ''}`),
    // Keep showing the last loaded copy if a refresh fails (UX: Inbox error state).
    placeholderData: (previous) => previous,
  })

export const useProjectSummary = (key: string) =>
  useQuery({
    queryKey: keys.summary(key),
    queryFn: () => api<ProjectSummary>(`/api/projects/${encodeURIComponent(key)}/summary/`),
  })

export const useRelease = (key: string, version: string) =>
  useQuery({
    queryKey: keys.release(key, version),
    queryFn: () =>
      api<ReleaseDetail>(`/api/projects/${encodeURIComponent(key)}/releases/${encodeURIComponent(version)}/`),
  })

/** Everything that can change when work is done: inbox, dashboards, releases. */
function useInvalidateWork() {
  const client = useQueryClient()
  return () => client.invalidateQueries({ queryKey: ['org', org()] })
}

export function useSnooze() {
  const invalidate = useInvalidateWork()
  return useMutation({
    mutationFn: ({ id, reason, until }: { id: string; reason: string; until: string }) =>
      api(`/api/inbox/${id}/snooze/`, { method: 'POST', body: { reason, until } }),
    onSuccess: invalidate,
  })
}

export function useUnsnooze() {
  const invalidate = useInvalidateWork()
  return useMutation({
    mutationFn: (id: string) => api(`/api/inbox/${id}/unsnooze/`, { method: 'POST' }),
    onSuccess: invalidate,
  })
}

export function useRetest() {
  const invalidate = useInvalidateWork()
  return useMutation({
    mutationFn: ({ displayId, outcome, evidence }: { displayId: string; outcome: 'passed' | 'failed'; evidence: string[] }) =>
      api(`/api/defects/${encodeURIComponent(displayId)}/retests/`, { method: 'POST', body: { outcome, evidence } }),
    onSuccess: invalidate,
  })
}

export function useSignOff(key: string, version: string) {
  const invalidate = useInvalidateWork()
  return useMutation({
    mutationFn: (reason: string | null) =>
      api<ReleaseDetail>(
        `/api/projects/${encodeURIComponent(key)}/releases/${encodeURIComponent(version)}/sign-off/`,
        { method: 'POST', body: { reason } },
      ),
    onSuccess: invalidate,
  })
}
