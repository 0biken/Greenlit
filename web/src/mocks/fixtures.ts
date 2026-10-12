// Sample data for the mock layer: one agency organisation testing three client products.
// Ages are relative to today so the Inbox always looks lived in.

import type {
  ActivityLine,
  Blocker,
  Inbox,
  InboxGroup,
  InboxItem,
  ProjectSummary,
  ReleaseDetail,
} from '../api/records'

const DAY = 86_400_000
export const daysAgo = (n: number, hour = 10, minute = 0) => {
  const d = new Date(Date.now() - n * DAY)
  d.setHours(hour, minute, 0, 0)
  return d.toISOString()
}
const daysAhead = (n: number) => new Date(Date.now() + n * DAY).toISOString().slice(0, 10)

export const ORG = { id: '00000000-0000-4000-8000-000000000001', slug: 'karma-groups', name: 'Karma Groups' }
export const ME = {
  id: '00000000-0000-4000-8000-0000000000aa',
  email: 'ada@karmagroups.example',
  name: 'Ada Okafor',
  mfa_enabled: true,
  memberships: [{ organisation: ORG, role: 'owner', status: 'active', needs_mfa: false }],
}

export const PROJECTS = [
  { id: '10000000-0000-4000-8000-000000000001', key: 'HUBE', name: 'Hube checkout', client_name: 'Hube Retail' },
  { id: '10000000-0000-4000-8000-000000000002', key: 'KOLA', name: 'Kola banking app', client_name: 'Kola Finance' },
  { id: '10000000-0000-4000-8000-000000000003', key: 'MARA', name: 'Mara bookings', client_name: 'Mara Travel' },
]

let n = 0
const item = (p: Omit<InboxItem, 'id' | 'since' | 'snoozed_until' | 'snooze_reason'>): InboxItem => ({
  id: `inbox-${++n}`,
  since: daysAgo(p.age_days),
  snoozed_until: null,
  snooze_reason: null,
  ...p,
})

const hube = { project_key: 'HUBE', project_name: 'Hube checkout' }
const kola = { project_key: 'KOLA', project_name: 'Kola banking app' }

export const INBOX_ITEMS: InboxItem[] = [
  item({ ...hube, group: 'closed_failed_retest', critical: true, status: 'retest_failed', display_id: 'BUG-1031', title: 'Cart total ignores discount code', age_days: 1, next_action: 'open', owner_name: 'Tunde Bello' }),
  item({ ...hube, group: 'needs_retest', critical: false, status: 'needs_retest', display_id: 'BUG-1042', title: 'Payment times out on card checkout', age_days: 4, next_action: 'retest', owner_name: 'Ada Okafor' }),
  item({ ...hube, group: 'needs_retest', critical: false, status: 'needs_retest', display_id: 'BUG-1048', title: 'App crashes when the cart is emptied', age_days: 2, next_action: 'retest', owner_name: 'Ada Okafor' }),
  item({ ...kola, group: 'needs_retest', critical: false, status: 'needs_retest', display_id: 'BUG-207', title: 'Transfer receipt shows the wrong currency symbol', age_days: 1, next_action: 'retest', owner_name: 'Ada Okafor' }),
  item({ ...kola, group: 'aging_defects', critical: false, status: 'open', display_id: 'BUG-198', title: 'Biometric prompt appears twice after app resume', age_days: 9, next_action: 'open', owner_name: 'Ifeoma Nwosu' }),
  item({ ...hube, group: 'unfiled_failures', critical: false, status: 'failed', display_id: 'TC-0057', title: 'Saved address is not offered at checkout', age_days: 1, next_action: 'file_defect', owner_name: null }),
  item({ ...kola, group: 'missing_evidence', critical: false, status: 'passed', display_id: 'TC-0112', title: 'Statement downloads as PDF', age_days: 3, next_action: 'attach_evidence', owner_name: null }),
  item({ ...hube, group: 'stale_tests', critical: false, status: 'stale', display_id: 'TC-0021', title: 'Guest user completes checkout', age_days: 42, next_action: 'run', owner_name: null }),
  item({ ...hube, group: 'stale_tests', critical: false, status: 'stale', display_id: 'TC-0034', title: 'Promo banner links to the right category', age_days: 31, next_action: 'run', owner_name: null }),
  item({ ...hube, group: 'uncovered', critical: false, status: 'uncovered', display_id: 'REQ-118', title: 'Refunds go back to the original card', age_days: 6, next_action: 'add_case', owner_name: null }),
  item({ ...kola, group: 'uncovered', critical: false, status: 'uncovered', display_id: 'REQ-044', title: 'Session ends after 5 minutes idle', age_days: 2, next_action: 'add_case', owner_name: null }),
]

export const GROUP_ORDER: InboxGroup[] = [
  'closed_failed_retest',
  'needs_retest',
  'aging_defects',
  'unfiled_failures',
  'missing_evidence',
  'stale_tests',
  'uncovered',
]

export function inboxFrom(items: InboxItem[]): Inbox {
  const active = items.filter((i) => !i.snoozed_until)
  const counts = Object.fromEntries(GROUP_ORDER.map((g) => [g, 0])) as Inbox['counts']
  for (const i of active) counts[i.group] += 1
  return {
    items: active,
    counts,
    snoozed: items.length - active.length,
    next_release: { project_key: 'HUBE', version: '2.4.1', due: daysAhead(3) },
  }
}

// ---- release 2.4.1 -------------------------------------------------------------------------

export const HUBE_BLOCKERS: Blocker[] = [
  { type: 'needs_retest', display_id: 'BUG-1042', title: 'Payment times out on card checkout', age_days: 4, owner_name: 'Ada Okafor' },
  { type: 'needs_retest', display_id: 'BUG-1048', title: 'App crashes when the cart is emptied', age_days: 2, owner_name: 'Ada Okafor' },
  { type: 'needs_retest', display_id: 'BUG-1050', title: 'Order email lists the wrong delivery date', age_days: 1, owner_name: 'Femi Adeyemi' },
  { type: 'closed_failed_retest', display_id: 'BUG-1031', title: 'Cart total ignores discount code', age_days: 1, owner_name: 'Tunde Bello' },
  { type: 'uncovered_critical', display_id: 'REQ-118', title: 'Refunds go back to the original card', age_days: 6, owner_name: null },
]

export function hubeRelease(blockers: Blocker[], signOff: ReleaseDetail['sign_off']): ReleaseDetail {
  const ready = blockers.length === 0
  return {
    project_key: 'HUBE',
    version: '2.4.1',
    name: 'Release 2.4.1',
    due: daysAhead(3),
    readiness: ready ? 'ready' : 'not_ready',
    blockers,
    coverage: { verified_pct: 82, verified: 18, on_hold: 3, failed: 1, not_run: 0, total_requirements: 22 },
    report: {
      display_id: 'RPT-14',
      state: signOff ? 'signed' : 'draft',
      summary: ready
        ? 'All blockers are resolved. 82% of requirements are verified with evidence.'
        : `Not ready yet. 82% of requirements are verified with evidence and ${blockers.length} blockers remain.`,
      sections: [
        {
          heading: 'Results by area',
          lines: [
            { text: 'Checkout: 14 of 16 cases passed in RUN-019; 2 failed and were filed.', refs: ['RUN-019', 'BUG-1042', 'BUG-1048'] },
            { text: 'Cart: 9 of 10 cases passed; the discount case failed its retest.', refs: ['RUN-019', 'BUG-1031'] },
            { text: 'Account: 12 of 12 cases passed.', refs: ['RUN-018'] },
          ],
        },
        {
          heading: 'Risks',
          lines: [
            { text: 'Refunds to the original card have no test case yet.', refs: ['REQ-118'] },
            { text: 'Guest checkout has not been run in 42 days.', refs: ['TC-0021'] },
          ],
        },
      ],
    },
    sign_off: signOff,
  }
}

// ---- project dashboards --------------------------------------------------------------------

const ACTIVITY: ActivityLine[] = [
  { at: daysAgo(0, 9, 42), actor: 'Ada Okafor', text: 'recorded RUN-019: 41 passed, 3 failed', refs: ['RUN-019'] },
  { at: daysAgo(0, 9, 15), actor: 'Femi Adeyemi', text: 'marked BUG-1050 fixed in Jira', refs: ['BUG-1050'] },
  { at: daysAgo(1, 17, 4), actor: 'Ada Okafor', text: 'retested BUG-1031: failed, evidence EV-0310', refs: ['BUG-1031', 'EV-0310'] },
  { at: daysAgo(1, 11, 30), actor: 'Tunde Bello', text: 'closed BUG-1031 in Jira', refs: ['BUG-1031'] },
  { at: daysAgo(2, 15, 2), actor: 'Ngozi Eze', text: 'approved TP-3 v1.4: 46 cases', refs: ['TP-3'] },
  { at: daysAgo(2, 10, 48), actor: 'Ada Okafor', text: 'verified BUG-1022 with EV-0298', refs: ['BUG-1022', 'EV-0298'] },
  { at: daysAgo(3, 16, 20), actor: 'Ada Okafor', text: 'accepted 6 draft cases for REQ-102', refs: ['REQ-102'] },
]

export const SUMMARIES: Record<string, ProjectSummary> = {
  HUBE: {
    key: 'HUBE',
    name: 'Hube checkout',
    client_name: 'Hube Retail',
    is_new: false,
    release: { version: '2.4.1', name: 'Release 2.4.1', due: daysAhead(3), readiness: 'not_ready', blockers: 5 },
    coverage: { verified_pct: 82, verified: 18, on_hold: 3, failed: 1, not_run: 0, total_requirements: 22 },
    open_work: [
      { kind: 'needs_retest', count: 3, oldest_days: 4 },
      { kind: 'retest_failed', count: 1, oldest_days: 1 },
      { kind: 'unfiled_failures', count: 1, oldest_days: 1 },
      { kind: 'stale', count: 2, oldest_days: 42 },
      { kind: 'uncovered', count: 1, oldest_days: 6 },
      { kind: 'missing_evidence', count: 0, oldest_days: null },
    ],
    activity: ACTIVITY,
    counts: { requirements: 22, cases: 46, runs: 19, open_defects: 6 },
  },
  KOLA: {
    key: 'KOLA',
    name: 'Kola banking app',
    client_name: 'Kola Finance',
    is_new: false,
    release: { version: '5.0.0', name: 'Release 5.0.0', due: daysAhead(12), readiness: 'not_ready', blockers: 2 },
    coverage: { verified_pct: 64, verified: 23, on_hold: 4, failed: 2, not_run: 7, total_requirements: 36 },
    open_work: [
      { kind: 'needs_retest', count: 1, oldest_days: 1 },
      { kind: 'retest_failed', count: 0, oldest_days: null },
      { kind: 'unfiled_failures', count: 0, oldest_days: null },
      { kind: 'stale', count: 0, oldest_days: null },
      { kind: 'uncovered', count: 1, oldest_days: 2 },
      { kind: 'missing_evidence', count: 1, oldest_days: 3 },
    ],
    activity: ACTIVITY.slice(2).map((a) => ({ ...a })),
    counts: { requirements: 36, cases: 71, runs: 8, open_defects: 4 },
  },
}

export function newProjectSummary(key: string, name = key, client_name = ''): ProjectSummary {
  return {
    key,
    name,
    client_name,
    is_new: true,
    release: null,
    coverage: null,
    open_work: [],
    activity: [],
    counts: { requirements: 0, cases: 0, runs: 0, open_defects: 0 },
  }
}
