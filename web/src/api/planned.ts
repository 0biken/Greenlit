// Response shapes for endpoints that are planned but not built yet (TASKS M6-03, M8-01..M8-09).
// The mock layer (src/mocks) serves these. When the real endpoint lands, delete the type here
// and use the generated one from schema.d.ts; TypeScript will point at every screen that differs.

import type { Status } from '../design/StatusChip'

/** FR-INB-01 groups, in the order the Inbox shows them. */
export type InboxGroup =
  | 'closed_failed_retest'
  | 'needs_retest'
  | 'aging_defects'
  | 'unfiled_failures'
  | 'missing_evidence'
  | 'stale_tests'
  | 'uncovered'

export type NextAction = 'retest' | 'run' | 'add_case' | 'open' | 'file_defect' | 'attach_evidence'

export type InboxItem = {
  id: string
  group: InboxGroup
  critical: boolean
  status: Status
  display_id: string // BUG-1042, TC-0021, REQ-118
  title: string
  project_key: string
  project_name: string
  age_days: number
  since: string // ISO date the item started waiting
  next_action: NextAction
  owner_name: string | null
  snoozed_until: string | null
  snooze_reason: string | null
}

export type Inbox = {
  items: InboxItem[]
  counts: Record<InboxGroup, number>
  snoozed: number
  next_release: { project_key: string; version: string; due: string } | null
}

export type Readiness = 'ready' | 'not_ready'

export type BlockerType =
  | 'needs_retest'
  | 'open_critical'
  | 'closed_failed_retest'
  | 'uncovered_critical'
  | 'unfiled_failure'

export type Blocker = {
  type: BlockerType
  display_id: string
  title: string
  age_days: number
  owner_name: string | null
}

export type SignOff = {
  by: string
  at: string
  readiness: Readiness
  reason: string | null
}

export type ReleaseDetail = {
  project_key: string
  version: string
  name: string
  due: string | null
  readiness: Readiness
  blockers: Blocker[]
  coverage: Coverage
  report: {
    display_id: string
    state: 'draft' | 'signed'
    summary: string
    sections: { heading: string; lines: { text: string; refs: string[] }[] }[]
  }
  sign_off: SignOff | null
}

export type Coverage = {
  verified_pct: number
  verified: number
  on_hold: number
  failed: number
  not_run: number
  total_requirements: number
}

export type ActivityLine = {
  at: string
  actor: string
  text: string
  refs: string[]
}

export type OpenWorkRow = {
  kind: 'needs_retest' | 'retest_failed' | 'stale' | 'uncovered' | 'missing_evidence' | 'unfiled_failures'
  count: number
  oldest_days: number | null
}

export type ProjectSummary = {
  key: string
  name: string
  client_name: string
  is_new: boolean
  release: { version: string; name: string; due: string | null; readiness: Readiness; blockers: number } | null
  coverage: Coverage | null
  open_work: OpenWorkRow[]
  activity: ActivityLine[]
  counts: { requirements: number; cases: number; runs: number; open_defects: number }
}
