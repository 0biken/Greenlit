import { Mark, type MarkKind } from './Mark'

// Every status in the product: mark + word + colour (brand guide 06, UX design rule 4).
// The product vocabulary (guide section 11) is fixed here so screens cannot drift from it.
export type Status =
  | 'passed'
  | 'failed'
  | 'retest_failed'
  | 'needs_retest'
  | 'blocked'
  | 'not_run'
  | 'stale'
  | 'draft'
  | 'verified'
  | 'uncovered'
  | 'missing_evidence'
  | 'open'
  | 'wont_fix'
  | 'deferred'
  | 'in_progress'

type Def = { mark: MarkKind; word: string; tone: 'pass' | 'fail' | 'hold' | 'open' | 'draft' | 'ver' }

export const STATUS: Record<Status, Def> = {
  passed: { mark: 'pass', word: 'Passed', tone: 'pass' },
  failed: { mark: 'fail', word: 'Failed', tone: 'fail' },
  retest_failed: { mark: 'fail', word: 'Retest failed', tone: 'fail' },
  needs_retest: { mark: 'hold', word: 'Needs retest', tone: 'hold' },
  blocked: { mark: 'hold', word: 'Blocked', tone: 'hold' },
  not_run: { mark: 'open', word: 'Not run', tone: 'open' },
  stale: { mark: 'stale', word: 'Stale', tone: 'open' },
  draft: { mark: 'draft', word: 'Draft', tone: 'draft' },
  verified: { mark: 'verified', word: 'Verified', tone: 'ver' },
  uncovered: { mark: 'open', word: 'No test cases', tone: 'open' },
  missing_evidence: { mark: 'hold', word: 'Missing evidence', tone: 'hold' },
  open: { mark: 'open', word: 'Open', tone: 'open' },
  // A decision, not a result: a dash, in the neutral tone.
  wont_fix: { mark: 'hold', word: "Won't fix", tone: 'open' },
  deferred: { mark: 'hold', word: 'Deferred', tone: 'open' },
  in_progress: { mark: 'open', word: 'In progress', tone: 'open' },
}

type Props = {
  status: Status
  /** A more exact word from the server, such as "Closed, retest failed". The mark stays. */
  word?: string
  /** Extra detail after the word, such as an age: "Stale · 42d". */
  detail?: string
  /** Fuller detail for screen readers: "Status: Needs retest, 4 days". */
  srDetail?: string
}

export function StatusChip({ status, word, detail, srDetail }: Props) {
  const def = { ...STATUS[status], word: word ?? STATUS[status].word }
  const spoken = `Status: ${def.word}${srDetail ? `, ${srDetail}` : detail ? `, ${detail}` : ''}`
  return (
    <span className={`chip chip-${def.tone}`} role="img" aria-label={spoken}>
      <Mark kind={def.mark} size={13} coloured={false} />
      <span aria-hidden="true">
        {def.word}
        {detail ? ` · ${detail}` : ''}
      </span>
    </span>
  )
}
