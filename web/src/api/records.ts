// The records behind the Inbox, the project dashboard and the release page, as the API returns
// them. Everything here is an alias of a generated type (`pnpm gen:api` → schema.d.ts), so a
// change to an endpoint shows up as a type error in the screen that uses it.

import type { Status } from '../design/StatusChip'
import type { components } from './schema'

type S = components['schemas']

/** FR-INB-01 groups, in the order the Inbox shows them. */
export type InboxGroup = S['GroupEnum']
export type NextAction = S['NextActionEnum']
/** `status` is one of the product's status words, so the chip can draw its mark. */
export type InboxItem = Omit<S['InboxItem'], 'status'> & { status: Status }
export type Inbox = Omit<S['Inbox'], 'items'> & { items: InboxItem[] }

export type Readiness = S['ReadinessEnum']
export type BlockerType = S['TypeEnum']
export type Blocker = S['Blocker']
export type Coverage = S['Coverage']
export type SignOff = S['SignOff']
export type ReleaseDetail = S['ReleaseDetail']

export type ActivityLine = S['Activity']
export type OpenWorkRow = S['OpenWork']
export type ProjectSummary = S['ProjectSummary']

export type Severity = S['SeverityEnum']
export type TrackerStatus = S['TrackerStatusEnum']
/** `chip` is one of the product's status words; the server picks it from the two statuses. */
export type DefectRow = Omit<S['DefectRow'], 'chip'> & { chip: Status }
export type DefectDetail = Omit<S['DefectDetail'], 'chip'> & { chip: Status }
export type EvidenceFile = S['Evidence']
export type DefectWrite = S['DefectWrite']

export type Outcome = S['ResultOutcomeEnum']
export type ReleaseRow = S['ReleaseRow']
export type PlanRow = S['PlanRow']
export type RunRow = S['RunRow']
export type RunCase = Omit<S['RunCase'], 'defects'> & {
  defects: (Omit<S['RunDefect'], 'chip'> & { chip: Status })[]
}
export type RunDetail = Omit<S['RunDetail'], 'cases'> & { cases: RunCase[] }

export type ShareLink = S['ShareLink']
export type ShareLinkCreated = S['ShareLinkCreated']
export type SharedReport = S['SharedReport']

export type RequirementRow = S['RequirementRow']
export type RequirementDetail = S['RequirementDetail']
export type RequirementWrite = S['RequirementWrite']
export type PlanDetail = S['PlanDetail']
export type PlanVersionDetail = S['PlanVersionDetail']
export type PlanCase = S['PlanCase']
export type PlanDiff = S['PlanDiff']
export type CaseDetail = S['CaseDetail']
export type CaseWrite = S['CaseWrite']
export type CaseEdit = S['PatchedCaseEdit']
