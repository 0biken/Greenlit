import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { serverMessage, useReview, useSource } from '../../api/queries'
import type { Severity, SourceDetail, SourceItem } from '../../api/records'
import { useHotkeys } from '../../app/hotkeys'
import { Button } from '../../design/Button'
import { IdTag } from '../../design/IdTag'
import { ErrorState, SkeletonRows } from '../../design/states'
import { StatusChip } from '../../design/StatusChip'
import { SEVERITY_WORD as PRIORITY_WORD } from '../defects/DefectsList'
import { NotFound } from '../NotFound'
import { ProjectNav } from '../projects/ProjectNav'
import { sourceStatus } from './SourcesList'
import '../defects/defects.css'
import '../plans/plans.css'
import './sources.css'

// Draft review (UX §7, M2-07): the source on the left with the passage a draft came from
// highlighted, the drafts on the right. A accepts, R rejects, Enter edits, J and K move.
// Nothing here animates: these keys are pressed many times in a sitting.

const REASONS = [
  { id: 'wrong', label: 'Wrong' },
  { id: 'duplicate', label: 'Duplicate' },
  { id: 'too_vague', label: 'Too vague' },
  { id: 'not_testable', label: 'Not testable' },
]
const ACCEPT_ALL = 20
/** Milliseconds since `at`: how long a draft was on screen before it was decided. */
const since = (at: number) => Math.round(performance.now() - at)

export function DraftReview() {
  const { projectKey = '', id = '' } = useParams()
  const source = useSource(projectKey.toUpperCase(), id)

  if (source.error instanceof ApiError && source.error.isNotFound) return <NotFound />
  if (source.isPending) return <SkeletonRows rows={6} />
  if (source.isError && !source.data) {
    return <ErrorState message="Couldn't load this document." onRetry={() => source.refetch()} />
  }
  return <Review projectKey={projectKey} source={source.data} />
}

function Review({ projectKey, source }: { projectKey: string; source: SourceDetail }) {
  const key = projectKey.toUpperCase()
  const base = `/${projectKey.toLowerCase()}`
  const act = useReview(key, source.id)
  const canReview = source.actions.review
  const waiting = useMemo(() => source.items.filter((i) => i.review_state === 'draft'), [source.items])
  const [currentNo, setCurrentNo] = useState<number | null>(null)
  const [mode, setMode] = useState<'read' | 'edit' | 'reject'>('read')
  const [copied, setCopied] = useState(false)
  const shownAt = useRef(0)
  const markRef = useRef<HTMLElement>(null)

  // The draft in front of the reviewer: the one they chose, else the first still waiting.
  const current = source.items.find((i) => i.number === currentNo) ?? waiting[0] ?? source.items[0] ?? null
  const isDraft = current?.review_state === 'draft'

  useEffect(() => {
    shownAt.current = performance.now()
    markRef.current?.scrollIntoView({ block: 'center' })
  }, [current?.number])

  function go(to: SourceItem | undefined) {
    if (!to) return
    setCurrentNo(to.number)
    setMode('read')
  }
  function move(delta: number) {
    const at = source.items.findIndex((i) => i.number === current?.number)
    go(source.items[Math.min(Math.max(at + delta, 0), source.items.length - 1)])
  }
  /** After deciding, move on to the next draft still waiting. */
  function next() {
    const after = waiting.filter((i) => i.number !== current?.number)
    setCurrentNo(after.find((i) => i.number > (current?.number ?? 0))?.number ?? after[0]?.number ?? null)
    setMode('read')
  }
  function decide(decision: 'accepted' | 'rejected', reason = '') {
    if (!current || !isDraft || !canReview || act.isPending) return
    const viewed_ms = since(shownAt.current)
    act.mutate({ do: 'decide', number: current.number, decision, reason, viewed_ms }, { onSuccess: next })
  }
  function acceptNext() {
    const numbers = waiting.slice(0, ACCEPT_ALL).map((i) => i.number)
    const viewed_ms = since(shownAt.current)
    act.mutate({ do: 'accept_many', numbers, viewed_ms }, { onSuccess: () => setCurrentNo(null) })
  }

  useHotkeys(
    {
      a: () => decide('accepted'),
      r: () => (mode === 'reject' ? decide('rejected') : isDraft && canReview && setMode('reject')),
      Enter: () => isDraft && canReview && setMode('edit'),
      Escape: () => setMode('read'),
      j: () => move(1),
      k: () => move(-1),
    },
    mode !== 'edit',
  )

  const busy = source.state === 'waiting' || source.state === 'parsing' || Boolean(source.job?.running)
  const summary = !source.job?.running && source.job?.state === 'succeeded' ? source.job.progress : ''

  return (
    <div className="defect">
      <header className="page-head">
        <div>
          <p className="crumbs">
            <Link to={base} className="mono">
              {key}
            </Link>
            <span aria-hidden="true">/</span>
            <Link to={`${base}/sources`}>Sources</Link>
          </p>
          <h1 className="page-title defect-heading">{source.title}</h1>
          <p className="page-sub defect-facts">
            <span>{source.drafts} to review</span>
            <span>{source.accepted} accepted</span>
            <span>{source.rejected} rejected</span>
            {source.fast_accepts ? (
              <span className="fast-accepts">
                {source.fast_accepts} accepted in under 2 seconds each
              </span>
            ) : null}
          </p>
        </div>
        {canReview && source.state === 'ready' && !busy ? (
          <Button disabled={act.isPending || Boolean(source.allowance_message)} onClick={() => act.mutate({ do: 'draft_again' })}>
            Draft again
          </Button>
        ) : null}
      </header>
      <ProjectNav projectKey={projectKey} />

      <div className="review-notes">
        {busy ? (
          <p className="review-note" role="status">
            <span className="prog" aria-hidden="true" /> {sourceStatus(source)}
            {source.job?.total ? ` (${source.job.done} of ${source.job.total})` : ''}. Drafts appear here as each
            section finishes.
          </p>
        ) : null}
        {source.state === 'failed' ? (
          <p className="field-error" role="alert">
            {source.failure}
          </p>
        ) : null}
        {source.job?.error && source.state !== 'failed' ? (
          <p className="review-note review-warn" role="alert">
            {source.job.error}
          </p>
        ) : null}
        {source.allowance_message && source.allowance_message !== source.job?.error ? (
          <p className="review-note review-warn">{source.allowance_message}</p>
        ) : null}
        {summary && source.left_out ? <p className="review-note">{summary}</p> : null}
        {act.isError ? (
          <p className="field-error" role="alert">
            {serverMessage(act.error) ?? "That didn't work. Try again."}
          </p>
        ) : null}
      </div>

      <div className="review-layout">
        <section className="review-source" aria-label="Source document">
          {source.text_pages.length ? (
            source.text_pages.map((page) => (
              <article key={page.page} className="review-page">
                <p className="overline">Page {page.page}</p>
                <PageText page={page} current={current} markRef={markRef} />
              </article>
            ))
          ) : (
            <p className="faint">{busy ? 'The text appears here once the document is read.' : 'No text to show.'}</p>
          )}
        </section>

        <section className="review-drafts" aria-label="Drafts">
          {source.gaps.length ? (
            <div className="gaps">
              <div className="gaps-head">
                <h2 className="overline">Questions for the product team</h2>
                <button
                  type="button"
                  className="link-button small"
                  onClick={() =>
                    navigator.clipboard
                      .writeText(source.gaps.map((g) => `- ${g}`).join('\n'))
                      .then(() => setCopied(true), () => setCopied(false))
                  }
                >
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
              <ul>
                {source.gaps.map((g) => (
                  <li key={g}>{g}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {canReview && waiting.length > 1 ? (
            <div className="review-all">
              <Button size="sm" disabled={act.isPending} onClick={acceptNext}>
                Accept {waiting.length > ACCEPT_ALL ? `the next ${ACCEPT_ALL}` : `all ${waiting.length}`}
              </Button>
              <span className="faint small">
                <kbd>A</kbd> accept <kbd>R</kbd> reject <kbd>Enter</kbd> edit <kbd>J</kbd> <kbd>K</kbd> move
              </span>
            </div>
          ) : null}

          {!source.items.length && !busy ? (
            <p className="faint">
              No requirements were drafted from this document.{' '}
              <Link to={`${base}/requirements/new`}>Add one by hand</Link>
            </p>
          ) : null}

          <ol className="draft-cards">
            {source.items.map((item) => {
              const on = item.number === current?.number
              return (
                <li key={item.number} className="draft-card" data-on={on || undefined} data-state={item.review_state}>
                  <button type="button" className="draft-card-head" onClick={() => go(item)} aria-current={on ? 'true' : undefined}>
                    {item.review_state === 'draft' ? (
                      <StatusChip status="draft" />
                    ) : item.review_state === 'accepted' ? (
                      <StatusChip status="verified" word="Accepted" />
                    ) : (
                      <StatusChip status="open" word="Rejected" />
                    )}
                    <span className="draft-card-title">{item.title}</span>
                    <span className="faint small">
                      {PRIORITY_WORD[item.priority]}
                      {item.page ? ` · p${item.page}` : ''}
                    </span>
                  </button>
                  {on && mode === 'edit' ? (
                    <EditDraft
                      item={item}
                      busy={act.isPending}
                      onCancel={() => setMode('read')}
                      onSave={(body) =>
                        act.mutate({ do: 'edit', number: item.number, body }, { onSuccess: () => setMode('read') })
                      }
                    />
                  ) : on ? (
                    <div className="draft-card-body">
                      <p className="pre">{item.text}</p>
                      {item.vague ? (
                        <p className="draft-flag">Vague as written: it needs a number or a rule to test against.</p>
                      ) : null}
                      {item.possible_duplicate_of ? (
                        <p className="draft-flag">
                          Possible duplicate of{' '}
                          <IdTag
                            id={item.possible_duplicate_of}
                            to={`${base}/requirements/${Number(item.possible_duplicate_of.split('-')[1])}`}
                          />
                        </p>
                      ) : null}
                      {item.assumptions.length ? (
                        <p className="draft-flag">Assumes: {item.assumptions.join('; ')}</p>
                      ) : null}
                      {item.review_state !== 'draft' ? (
                        item.review_state === 'accepted' ? (
                          <p className="faint small">
                            Now <IdTag id={item.display_id} to={`${base}/requirements/${item.number}`} />
                          </p>
                        ) : null
                      ) : !canReview ? null : mode === 'reject' ? (
                        <div className="draft-actions" role="group" aria-label="Why reject it? Optional">
                          <span className="faint small">Why? (optional)</span>
                          {REASONS.map((r) => (
                            <Button key={r.id} size="sm" disabled={act.isPending} onClick={() => decide('rejected', r.id)}>
                              {r.label}
                            </Button>
                          ))}
                          <Button size="sm" variant="danger" disabled={act.isPending} onClick={() => decide('rejected')}>
                            Reject <kbd>R</kbd>
                          </Button>
                          <Button size="sm" variant="quiet" onClick={() => setMode('read')}>
                            Cancel
                          </Button>
                        </div>
                      ) : (
                        <div className="draft-actions">
                          <Button size="sm" variant="primary" disabled={act.isPending} onClick={() => decide('accepted')}>
                            Accept <kbd>A</kbd>
                          </Button>
                          <Button size="sm" onClick={() => setMode('edit')}>
                            Edit <kbd>Enter</kbd>
                          </Button>
                          <Button size="sm" onClick={() => setMode('reject')}>
                            Reject <kbd>R</kbd>
                          </Button>
                        </div>
                      )}
                    </div>
                  ) : null}
                </li>
              )
            })}
          </ol>
        </section>
      </div>
    </div>
  )
}

/** One page of the source, with the current draft's passage marked if it is on this page. */
function PageText({
  page,
  current,
  markRef,
}: {
  page: SourceDetail['text_pages'][number]
  current: SourceItem | null
  markRef: React.RefObject<HTMLElement | null>
}) {
  const start = current?.start != null ? current.start - page.start : -1
  const end = current?.end != null ? current.end - page.start : -1
  if (start < 0 || start >= page.text.length || end <= start) return <p className="pre review-text">{page.text}</p>
  return (
    <p className="pre review-text">
      {page.text.slice(0, start)}
      <mark ref={markRef} className="passage">
        {page.text.slice(start, end)}
      </mark>
      {page.text.slice(end)}
    </p>
  )
}

function EditDraft({
  item,
  busy,
  onSave,
  onCancel,
}: {
  item: SourceItem
  busy: boolean
  onSave: (body: { title: string; text: string; priority: Severity }) => void
  onCancel: () => void
}) {
  const [priority, setPriority] = useState<Severity>(item.priority)
  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    onSave({ title: String(form.get('title') ?? '').trim(), text: String(form.get('text') ?? '').trim(), priority })
  }
  return (
    <form className="draft-card-body draft-edit" onSubmit={submit}>
      <label className="field">
        <span className="field-label">Title</span>
        <input className="input" name="title" required maxLength={200} defaultValue={item.title} autoFocus />
      </label>
      <label className="field">
        <span className="field-label">What must be true</span>
        <textarea className="textarea" name="text" rows={4} required defaultValue={item.text} />
      </label>
      <fieldset className="segmented">
        <legend className="field-label">Priority</legend>
        {(Object.keys(PRIORITY_WORD) as Severity[]).map((p) => (
          <label key={p} className="segment">
            <input type="radio" name="priority" checked={priority === p} onChange={() => setPriority(p)} />
            <span>{PRIORITY_WORD[p]}</span>
          </label>
        ))}
      </fieldset>
      <div className="draft-actions">
        <Button size="sm" type="submit" variant="primary" disabled={busy}>
          {busy ? 'Saving…' : 'Save'}
        </Button>
        <Button size="sm" variant="quiet" onClick={onCancel}>
          Cancel
        </Button>
        <span className="faint small">It stays a draft, with its source, until you accept it.</span>
      </div>
    </form>
  )
}
