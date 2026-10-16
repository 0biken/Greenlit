import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useHotkeys } from '../../app/hotkeys'
import { Button } from '../../design/Button'
import { StatusChip } from '../../design/StatusChip'
import './review.css'

// What every draft review screen shares (UX §7, M2-07): the keys, moving on after a decision,
// the reject reasons, the notes above the drafts and the gaps list. The screens differ only
// in what a draft is and what is shown beside it (a PRD passage, or the requirement a case
// covers). Nothing here animates: these keys are pressed many times in a sitting.

export const REASONS = [
  { id: 'wrong', label: 'Wrong' },
  { id: 'duplicate', label: 'Duplicate' },
  { id: 'too_vague', label: 'Too vague' },
  { id: 'not_testable', label: 'Not testable' },
]
export const ACCEPT_ALL = 20

export type Reviewable = { number: number; review_state: 'draft' | 'accepted' | 'rejected' }
export type Mode = 'read' | 'edit' | 'reject'
export type Decide = (decision: 'accepted' | 'rejected', reason?: string) => void

/** Milliseconds since `at`: how long a draft was on screen before it was decided. */
const since = (at: number) => Math.round(performance.now() - at)

/**
 * Which draft is in front of the reviewer, and the keys that act on it: A accept, R reject
 * (R again to reject without a reason), Enter edit, J and K move, Escape back out.
 */
export function useReviewCursor<T extends Reviewable>(
  items: T[],
  options: {
    canReview: boolean
    busy: boolean
    onDecide: (item: T, decision: 'accepted' | 'rejected', reason: string, viewedMs: number, done: () => void) => void
  },
) {
  const waiting = useMemo(() => items.filter((i) => i.review_state === 'draft'), [items])
  const [currentNo, setCurrentNo] = useState<number | null>(null)
  const [mode, setMode] = useState<Mode>('read')
  const shownAt = useRef(0)

  // The one they chose, else the first still waiting, else the first of all.
  const current = items.find((i) => i.number === currentNo) ?? waiting[0] ?? items[0] ?? null
  const isDraft = current?.review_state === 'draft'
  const canAct = isDraft && options.canReview

  useEffect(() => {
    shownAt.current = performance.now()
  }, [current?.number])

  function go(to: T | undefined) {
    if (!to) return
    setCurrentNo(to.number)
    setMode('read')
  }
  function move(delta: number) {
    const at = items.findIndex((i) => i.number === current?.number)
    go(items[Math.min(Math.max(at + delta, 0), items.length - 1)])
  }
  /** After deciding, move on to the next draft still waiting. */
  function next() {
    const after = waiting.filter((i) => i.number !== current?.number)
    setCurrentNo(after.find((i) => i.number > (current?.number ?? 0))?.number ?? after[0]?.number ?? null)
    setMode('read')
  }
  const decide: Decide = (decision, reason = '') => {
    if (!current || !canAct || options.busy) return
    options.onDecide(current, decision, reason, since(shownAt.current), next)
  }

  useHotkeys(
    {
      a: () => decide('accepted'),
      r: () => (mode === 'reject' ? decide('rejected') : canAct && setMode('reject')),
      Enter: () => canAct && setMode('edit'),
      Escape: () => setMode('read'),
      j: () => move(1),
      k: () => move(-1),
    },
    mode !== 'edit',
  )

  return {
    current,
    waiting,
    mode,
    setMode,
    go,
    decide,
    /** How long the current draft has been on screen; for accept-all. */
    viewedMs: () => since(shownAt.current),
    reset: () => setCurrentNo(null),
  }
}

export type JobNote = {
  running: boolean
  state: string
  progress: string
  done: number
  total: number
  error: string
} | null

/** The strip above the drafts: progress, what went wrong, and what was left out. */
export function ReviewNotes({
  job,
  busyWord,
  failure,
  allowance,
  leftOut,
  actionError,
}: {
  job: JobNote
  /** What is happening while it runs, in the product's words. */
  busyWord: string | null
  failure?: string
  allowance: string
  leftOut: number
  actionError: string | null
}) {
  const summary = job && !job.running && job.state === 'succeeded' && leftOut ? job.progress : ''
  return (
    <div className="review-notes">
      {busyWord ? (
        <p className="review-note" role="status">
          <span className="prog" aria-hidden="true" /> {busyWord}
          {job?.total ? ` (${job.done} of ${job.total})` : ''}. Drafts appear here as each part finishes.
        </p>
      ) : null}
      {failure ? (
        <p className="field-error" role="alert">
          {failure}
        </p>
      ) : null}
      {job?.error && !failure ? (
        <p className="review-note review-warn" role="alert">
          {job.error}
        </p>
      ) : null}
      {allowance && allowance !== job?.error ? <p className="review-note review-warn">{allowance}</p> : null}
      {summary ? <p className="review-note">{summary}</p> : null}
      {actionError ? (
        <p className="field-error" role="alert">
          {actionError}
        </p>
      ) : null}
    </div>
  )
}

/** The questions the AI could not answer from the source. One of its most useful outputs. */
export function GapsBox({ gaps }: { gaps: string[] }) {
  const [copied, setCopied] = useState(false)
  if (!gaps.length) return null
  return (
    <div className="gaps">
      <div className="gaps-head">
        <h2 className="overline">Questions for the product team</h2>
        <button
          type="button"
          className="link-button small"
          onClick={() =>
            navigator.clipboard.writeText(gaps.map((g) => `- ${g}`).join('\n')).then(
              () => setCopied(true),
              () => setCopied(false),
            )
          }
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <ul>
        {gaps.map((g) => (
          <li key={g}>{g}</li>
        ))}
      </ul>
    </div>
  )
}

/** Accept the next drafts in one go, never more than 20, with the keys as a reminder. */
export function AcceptAll({ waiting, busy, onAccept }: { waiting: number; busy: boolean; onAccept: () => void }) {
  if (waiting < 2) return null
  return (
    <div className="review-all">
      <Button size="sm" disabled={busy} onClick={onAccept}>
        Accept {waiting > ACCEPT_ALL ? `the next ${ACCEPT_ALL}` : `all ${waiting}`}
      </Button>
      <span className="faint small">
        <kbd>A</kbd> accept <kbd>R</kbd> reject <kbd>Enter</kbd> edit <kbd>J</kbd> <kbd>K</kbd> move
      </span>
    </div>
  )
}

export function ReviewChip({ state }: { state: Reviewable['review_state'] }) {
  if (state === 'draft') return <StatusChip status="draft" />
  if (state === 'accepted') return <StatusChip status="verified" word="Accepted" />
  return <StatusChip status="open" word="Rejected" />
}

/** The buttons under the current draft: accept, edit, reject, or the reasons to reject. */
export function DraftActions({
  mode,
  setMode,
  decide,
  busy,
}: {
  mode: Mode
  setMode: (mode: Mode) => void
  decide: Decide
  busy: boolean
}) {
  if (mode === 'reject') {
    return (
      <div className="draft-actions" role="group" aria-label="Why reject it? Optional">
        <span className="faint small">Why? (optional)</span>
        {REASONS.map((r) => (
          <Button key={r.id} size="sm" disabled={busy} onClick={() => decide('rejected', r.id)}>
            {r.label}
          </Button>
        ))}
        <Button size="sm" variant="danger" disabled={busy} onClick={() => decide('rejected')}>
          Reject <kbd>R</kbd>
        </Button>
        <Button size="sm" variant="quiet" onClick={() => setMode('read')}>
          Cancel
        </Button>
      </div>
    )
  }
  return (
    <div className="draft-actions">
      <Button size="sm" variant="primary" disabled={busy} onClick={() => decide('accepted')}>
        Accept <kbd>A</kbd>
      </Button>
      <Button size="sm" onClick={() => setMode('edit')}>
        Edit <kbd>Enter</kbd>
      </Button>
      <Button size="sm" onClick={() => setMode('reject')}>
        Reject <kbd>R</kbd>
      </Button>
    </div>
  )
}

/** A note on a draft the reviewer should weigh: vague, a possible duplicate, an assumption. */
export function DraftFlag({ children }: { children: ReactNode }) {
  return <p className="draft-flag">{children}</p>
}
