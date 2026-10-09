import { delay, http, HttpResponse } from 'msw'
import type { InboxItem, ReleaseDetail } from '../api/planned'
import {
  HUBE_BLOCKERS,
  INBOX_ITEMS,
  ME,
  ORG,
  PROJECTS,
  SUMMARIES,
  hubeRelease,
  inboxFrom,
  newProjectSummary,
} from './fixtures'

// In-memory state so actions (snooze, retest, sign-off) change what later requests return.
let items: InboxItem[] = structuredClone(INBOX_ITEMS)
let blockers = structuredClone(HUBE_BLOCKERS)
let signOff: ReleaseDetail['sign_off'] = null

const wait = () => delay(import.meta.env.MODE === 'test' ? 0 : 280 + Math.random() * 220)

/** Endpoints that are planned but not built yet (M5, M6, M8). Always mocked in development. */
export const plannedHandlers = [
  http.get('/api/inbox/', async ({ request }) => {
    await wait()
    const snoozed = new URL(request.url).searchParams.get('snoozed') === '1'
    if (snoozed) {
      return HttpResponse.json({ ...inboxFrom(items), items: items.filter((i) => i.snoozed_until) })
    }
    return HttpResponse.json(inboxFrom(items))
  }),

  http.post('/api/inbox/:id/snooze/', async ({ params, request }) => {
    await wait()
    const { reason, until } = (await request.json()) as { reason: string; until: string }
    if (!reason?.trim()) return HttpResponse.json({ reason: ['Give a reason.'] }, { status: 400 })
    items = items.map((i) => (i.id === params.id ? { ...i, snoozed_until: until, snooze_reason: reason } : i))
    return new HttpResponse(null, { status: 204 })
  }),

  http.post('/api/inbox/:id/unsnooze/', async ({ params }) => {
    await wait()
    items = items.map((i) => (i.id === params.id ? { ...i, snoozed_until: null, snooze_reason: null } : i))
    return new HttpResponse(null, { status: 204 })
  }),

  // M5-05: a retest with evidence. Passed gives Verified; failed gives Retest failed.
  http.post('/api/defects/:displayId/retests/', async ({ params, request }) => {
    await wait()
    const { outcome, evidence } = (await request.json()) as { outcome: 'passed' | 'failed'; evidence: string[] }
    if (!evidence?.length) return HttpResponse.json({ evidence: ['Attach evidence.'] }, { status: 400 })
    const id = String(params.displayId).toUpperCase()
    if (outcome === 'passed') {
      items = items.filter((i) => i.display_id !== id)
      blockers = blockers.filter((b) => b.display_id !== id)
    } else {
      items = items.map((i) =>
        i.display_id === id ? { ...i, group: 'closed_failed_retest', critical: true, status: 'retest_failed', age_days: 0, next_action: 'open' } : i,
      )
      blockers = blockers.map((b) => (b.display_id === id ? { ...b, type: 'closed_failed_retest', age_days: 0 } : b))
    }
    return HttpResponse.json({ display_id: id, outcome })
  }),

  http.get('/api/projects/:key/summary/', async ({ params }) => {
    await wait()
    const key = String(params.key).toUpperCase()
    const summary = SUMMARIES[key]
    if (!summary) {
      const p = PROJECTS.find((x) => x.key === key)
      return HttpResponse.json(newProjectSummary(key, p?.name, p?.client_name))
    }
    if (key === 'HUBE' && summary.release) {
      const r = hubeRelease(blockers, signOff)
      return HttpResponse.json({
        ...summary,
        release: { ...summary.release, readiness: r.readiness, blockers: blockers.length },
        open_work: summary.open_work.map((w) =>
          w.kind === 'needs_retest' ? { ...w, count: blockers.filter((b) => b.type === 'needs_retest').length } : w,
        ),
      })
    }
    return HttpResponse.json(summary)
  }),

  http.get('/api/projects/:key/releases/:version/', async ({ params }) => {
    await wait()
    if (String(params.key).toUpperCase() !== 'HUBE' || params.version !== '2.4.1') {
      return HttpResponse.json({ detail: 'Not found.' }, { status: 404 })
    }
    return HttpResponse.json(hubeRelease(blockers, signOff))
  }),

  http.post('/api/projects/:key/releases/:version/sign-off/', async ({ request }) => {
    await wait()
    const { reason } = (await request.json()) as { reason?: string }
    const ready = blockers.length === 0
    if (!ready && !reason?.trim()) {
      return HttpResponse.json({ reason: ['Say why you are signing off while not ready.'] }, { status: 400 })
    }
    signOff = {
      by: ME.name,
      at: new Date().toISOString(),
      readiness: ready ? 'ready' : 'not_ready',
      reason: reason?.trim() || null,
    }
    return HttpResponse.json(hubeRelease(blockers, signOff))
  }),
]

/** Stand-ins for endpoints that do exist, for previewing the UI with no backend (VITE_MOCKS=all). */
export const backendHandlers = [
  http.get('/_allauth/browser/v1/config', () => HttpResponse.json({ status: 200, data: {} })),
  http.get('/_allauth/browser/v1/auth/session', () =>
    HttpResponse.json({ status: 200, data: { user: { email: ME.email } }, meta: { is_authenticated: true } }),
  ),
  http.post('/_allauth/browser/v1/auth/login', () =>
    HttpResponse.json({ status: 200, data: {}, meta: { is_authenticated: true } }),
  ),
  http.delete('/_allauth/browser/v1/auth/session', () =>
    HttpResponse.json({ status: 401, data: { flows: [] }, meta: { is_authenticated: false } }, { status: 401 }),
  ),
  http.get('/api/me/', () => HttpResponse.json(ME)),
  http.get('/api/org/', () => HttpResponse.json({ ...ORG, role: 'owner' })),
  http.get('/api/flags/', () => HttpResponse.json({ enabled: ['plan', 'shot', 'imp', 'tc', 'run', 'def', 'inb', 'rpt'] })),
  http.get('/api/projects/', async () => {
    await wait()
    return HttpResponse.json(PROJECTS)
  }),
  http.get('/api/projects/:key/', ({ params }) => {
    const p = PROJECTS.find((x) => x.key === String(params.key).toUpperCase())
    return p ? HttpResponse.json(p) : HttpResponse.json({ detail: 'Not found.' }, { status: 404 })
  }),
  http.get('/api/members/', () =>
    HttpResponse.json([
      { user_id: ME.id, email: ME.email, name: ME.name, role: 'owner', status: 'active' },
      { user_id: 'u2', email: 'ngozi@karmagroups.example', name: 'Ngozi Eze', role: 'qa_lead', status: 'active' },
      { user_id: 'u3', email: 'femi@karmagroups.example', name: 'Femi Adeyemi', role: 'developer', status: 'active' },
    ]),
  ),
]
