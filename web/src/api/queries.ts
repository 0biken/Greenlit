import { QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api, download, getCurrentOrg } from './client'
import type {
  DefectDetail,
  DefectRow,
  DefectWrite,
  Inbox,
  Outcome,
  PlanRow,
  ProjectSummary,
  ReleaseDetail,
  ReleaseRow,
  RunDetail,
  RunRow,
  ShareLink,
  ShareLinkCreated,
  SharedReport,
  TrackerStatus,
} from './records'
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
  projectMembers: (key: string) => ['org', org(), 'project', key, 'members'] as const,
  defects: (key: string, filters: DefectFilters) => ['org', org(), 'project', key, 'defects', filters] as const,
  defect: (key: string, id: string) => ['org', org(), 'project', key, 'defect', id] as const,
  releases: (key: string) => ['org', org(), 'project', key, 'releases'] as const,
  plans: (key: string) => ['org', org(), 'project', key, 'plans'] as const,
  runs: (key: string) => ['org', org(), 'project', key, 'runs'] as const,
  run: (key: string, id: string) => ['org', org(), 'project', key, 'run', id] as const,
  shareLinks: (key: string, version: string) => ['org', org(), 'project', key, 'release', version, 'links'] as const,
  shared: (token: string) => ['shared', token] as const,
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

type UploadStarted = components['schemas']['UploadStarted']

/** Send one evidence file through the file service: ask for a place, send the bytes, confirm. */
export async function uploadEvidence(projectKey: string, file: File): Promise<string> {
  const started = await api<UploadStarted>(`/api/projects/${encodeURIComponent(projectKey)}/files/`, {
    method: 'POST',
    body: { kind: 'evidence', name: file.name, size: file.size },
  })
  const { method, url, fields, headers } = started.upload
  let body: BodyInit = file
  if (method === 'POST') {
    // Object storage takes a form post: its signed fields first, the file last.
    const form = new FormData()
    for (const [name, value] of Object.entries(fields)) form.append(name, value)
    form.append('file', file)
    body = form
  }
  const sent = await fetch(url, { method, headers: method === 'POST' ? undefined : headers, body })
  if (!sent.ok) throw new ApiError(sent.status, null, 'upload')
  await api(`/api/files/${started.file.id}/complete/`, { method: 'POST' })
  return started.file.id
}

export type RetestInput = {
  projectKey: string
  displayId: string
  outcome: 'passed' | 'failed'
  files: File[]
  /** Called as each file starts and finishes, for the per-file progress lines. */
  onProgress?: (index: number, state: 'uploading' | 'attached') => void
}

export function useRetest() {
  const invalidate = useInvalidateWork()
  return useMutation({
    mutationFn: async ({ projectKey, displayId, outcome, files, onProgress }: RetestInput) => {
      const ids: string[] = []
      for (const [index, file] of files.entries()) {
        onProgress?.(index, 'uploading')
        ids.push(await uploadEvidence(projectKey, file))
        onProgress?.(index, 'attached')
      }
      return api(
        `/api/projects/${encodeURIComponent(projectKey)}/defects/${encodeURIComponent(displayId)}/retests/`,
        { method: 'POST', body: { outcome, evidence_file_ids: ids } },
      )
    },
    onSuccess: invalidate,
  })
}

/** The server's own words for a refused request, when it gave any. */
export function serverMessage(error: unknown): string | null {
  if (!(error instanceof ApiError) || !error.body || typeof error.body !== 'object') return null
  const detail = (error.body as { detail?: unknown }).detail
  return typeof detail === 'string' ? detail : null
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

// ---- defects -------------------------------------------------------------------------------

export type DefectFilters = { state?: string; severity?: string; q?: string }
export type ProjectMember = components['schemas']['ProjectMember']

const project = (key: string) => `/api/projects/${encodeURIComponent(key)}`
const defectUrl = (key: string, id: string) => `${project(key)}/defects/${encodeURIComponent(id)}/`

export const useProjectMembers = (key: string) =>
  useQuery({ queryKey: keys.projectMembers(key), queryFn: () => api<ProjectMember[]>(`${project(key)}/members/`) })

export const useDefects = (key: string, filters: DefectFilters) =>
  useQuery({
    queryKey: keys.defects(key, filters),
    queryFn: () => {
      const query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v) as [string, string][])
      return api<DefectRow[]>(`${project(key)}/defects/${query.size ? `?${query}` : ''}`)
    },
    placeholderData: (previous) => previous,
  })

export const useDefect = (key: string, id: string) =>
  useQuery({ queryKey: keys.defect(key, id), queryFn: () => api<DefectDetail>(defectUrl(key, id)) })

export type DefectInput = Omit<DefectWrite, 'evidence_file_ids'> & { files?: File[] }

export function useCreateDefect(key: string) {
  const invalidate = useInvalidateWork()
  return useMutation({
    mutationFn: async ({ files = [], ...body }: DefectInput) => {
      const ids: string[] = []
      for (const file of files) ids.push(await uploadEvidence(key, file))
      return api<DefectDetail>(`${project(key)}/defects/`, {
        method: 'POST',
        body: { ...body, evidence_file_ids: ids },
      })
    },
    onSuccess: invalidate,
  })
}

export function useEditDefect(key: string, id: string) {
  const invalidate = useInvalidateWork()
  return useMutation({
    mutationFn: (body: Partial<DefectWrite>) => api<DefectDetail>(defectUrl(key, id), { method: 'PATCH', body }),
    onSuccess: invalidate,
  })
}

export function useSetDefectStatus(key: string, id: string) {
  const invalidate = useInvalidateWork()
  return useMutation({
    mutationFn: (status: TrackerStatus) => api(`${defectUrl(key, id)}status/`, { method: 'POST', body: { status } }),
    onSuccess: invalidate,
  })
}

export function useDecideDefect(key: string, id: string) {
  const invalidate = useInvalidateWork()
  return useMutation({
    mutationFn: (body: { decision: 'wont_fix' | 'deferred'; reason: string }) =>
      api(`${defectUrl(key, id)}decision/`, { method: 'POST', body }),
    onSuccess: invalidate,
  })
}

/** A short-lived link to a stored file. Files still being scanned are not served yet (409). */
export const fileDownloadUrl = async (fileId: string) =>
  (await api<components['schemas']['Download']>(`/api/files/${fileId}/download/`)).url

// ---- releases, plans and runs ----------------------------------------------------------------

export const useReleases = (key: string) =>
  useQuery({ queryKey: keys.releases(key), queryFn: () => api<ReleaseRow[]>(`${project(key)}/releases/`) })

export const usePlans = (key: string, enabled = true) =>
  useQuery({ queryKey: keys.plans(key), queryFn: () => api<PlanRow[]>(`${project(key)}/plans/`), enabled })

export const useRuns = (key: string) =>
  useQuery({ queryKey: keys.runs(key), queryFn: () => api<RunRow[]>(`${project(key)}/runs/`) })

export const useRun = (key: string, id: string) =>
  useQuery({
    queryKey: keys.run(key, id),
    queryFn: () => api<RunDetail>(`${project(key)}/runs/${encodeURIComponent(id)}/`),
    // The run screen keeps its own copy of what was typed; do not swap it out mid-run.
    refetchOnWindowFocus: false,
  })

export function useCreateRelease(key: string) {
  const invalidate = useInvalidateWork()
  return useMutation({
    mutationFn: (body: { version: string; due?: string | null }) =>
      api<ReleaseRow>(`${project(key)}/releases/`, { method: 'POST', body }),
    onSuccess: invalidate,
  })
}

export function useStartRun(key: string) {
  const invalidate = useInvalidateWork()
  return useMutation({
    mutationFn: (body: { plan: number; release: string; build: string; environment: string }) =>
      api<RunDetail>(`${project(key)}/runs/`, { method: 'POST', body }),
    onSuccess: invalidate,
  })
}

/** Save one result. PUT, so sending it again after a dropped connection is harmless. */
export const saveResult = (key: string, run: number, resultId: string, outcome: Outcome, note: string) =>
  api(`${project(key)}/runs/${run}/results/${resultId}/`, { method: 'PUT', body: { outcome, note } })

export async function attachResultEvidence(key: string, run: number, resultId: string, files: File[]) {
  const ids: string[] = []
  for (const file of files) ids.push(await uploadEvidence(key, file))
  return api<components['schemas']['RunEvidence'][]>(
    `${project(key)}/runs/${run}/results/${resultId}/evidence/`,
    { method: 'POST', body: { file_ids: ids } },
  )
}

export function useCompleteRun(key: string, run: number) {
  const invalidate = useInvalidateWork()
  return useMutation({
    mutationFn: () => api<RunDetail>(`${project(key)}/runs/${run}/complete/`, { method: 'POST' }),
    onSuccess: invalidate,
  })
}

// ---- signed report: PDF and share links --------------------------------------------------------

const releaseUrl = (key: string, version: string) => `${project(key)}/releases/${encodeURIComponent(version)}`

export const downloadReportPdf = (key: string, version: string) => download(`${releaseUrl(key, version)}/report.pdf`)

export const useShareLinks = (key: string, version: string, enabled: boolean) =>
  useQuery({
    queryKey: keys.shareLinks(key, version),
    queryFn: () => api<ShareLink[]>(`${releaseUrl(key, version)}/share-links/`),
    enabled,
  })

export function useCreateShareLink(key: string, version: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<ShareLinkCreated>(`${releaseUrl(key, version)}/share-links/`, { method: 'POST', body: {} }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.shareLinks(key, version) }),
  })
}

export function useRevokeShareLink(key: string, version: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api(`${releaseUrl(key, version)}/share-links/${id}/`, { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.shareLinks(key, version) }),
  })
}

/** What a share link shows. No sign-in and no organisation: the token is the credential. */
export const useSharedReport = (token: string) =>
  useQuery({
    queryKey: keys.shared(token),
    queryFn: () => api<SharedReport>(`/api/shared/${encodeURIComponent(token)}/`, { noOrg: true }),
    retry: false,
  })

export const downloadSharedPdf = (token: string) =>
  download(`/api/shared/${encodeURIComponent(token)}/report.pdf`, { noOrg: true })
