import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { serverMessage, useReview, useSource } from '../../api/queries'
import type { Severity, SourceDetail, SourceItem } from '../../api/records'
import { Button } from '../../design/Button'
import { IdTag } from '../../design/IdTag'
import { ErrorState, SkeletonRows } from '../../design/states'
import { SEVERITY_WORD as PRIORITY_WORD } from '../defects/DefectsList'
import { NotFound } from '../NotFound'
import { ProjectNav } from '../projects/ProjectNav'
import {
  ACCEPT_ALL,
  AcceptAll,
  DraftActions,
  DraftFlag,
  GapsBox,
  ReviewChip,
  ReviewNotes,
  useReviewCursor,
} from '../review/review'
import { sourceStatus } from './SourcesList'
import '../defects/defects.css'
import '../plans/plans.css'

// Requirement drafts from one source (UX §7, M2-07): the source on the left with the passage
// a draft came from highlighted, the drafts on the right. The keys and the rest of the review
// behaviour are shared with the case review screen (features/review).

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
  const markRef = useRef<HTMLElement>(null)
  const review = useReviewCursor(source.items, {
    canReview,
    busy: act.isPending,
    onDecide: (item, decision, reason, viewed_ms, done) =>
      act.mutate({ do: 'decide', number: item.number, decision, reason, viewed_ms }, { onSuccess: done }),
  })
  const { current, waiting, mode, setMode } = review

  useEffect(() => {
    markRef.current?.scrollIntoView({ block: 'center' })
  }, [current?.number])

  const busy = source.state === 'waiting' || source.state === 'parsing' || Boolean(source.job?.running)

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
              <span className="fast-accepts">{source.fast_accepts} accepted in under 2 seconds each</span>
            ) : null}
          </p>
        </div>
        {canReview && source.state === 'ready' && !busy ? (
          <Button
            disabled={act.isPending || Boolean(source.allowance_message)}
            onClick={() => act.mutate({ do: 'draft_again' })}
          >
            Draft again
          </Button>
        ) : null}
      </header>
      <ProjectNav projectKey={projectKey} />

      <ReviewNotes
        job={source.job}
        busyWord={busy ? sourceStatus(source) : null}
        failure={source.state === 'failed' ? source.failure : undefined}
        allowance={source.allowance_message}
        leftOut={source.left_out}
        actionError={act.isError ? (serverMessage(act.error) ?? "That didn't work. Try again.") : null}
      />

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
          <GapsBox gaps={source.gaps} />
          {canReview ? (
            <AcceptAll
              waiting={waiting.length}
              busy={act.isPending}
              onAccept={() =>
                act.mutate(
                  {
                    do: 'accept_many',
                    numbers: waiting.slice(0, ACCEPT_ALL).map((i) => i.number),
                    viewed_ms: review.viewedMs(),
                  },
                  { onSuccess: review.reset },
                )
              }
            />
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
                  <button
                    type="button"
                    className="draft-card-head"
                    onClick={() => review.go(item)}
                    aria-current={on ? 'true' : undefined}
                  >
                    <ReviewChip state={item.review_state} />
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
                        <DraftFlag>Vague as written: it needs a number or a rule to test against.</DraftFlag>
                      ) : null}
                      {item.possible_duplicate_of ? (
                        <DraftFlag>
                          Possible duplicate of{' '}
                          <IdTag
                            id={item.possible_duplicate_of}
                            to={`${base}/requirements/${Number(item.possible_duplicate_of.split('-')[1])}`}
                          />
                        </DraftFlag>
                      ) : null}
                      {item.assumptions.length ? <DraftFlag>Assumes: {item.assumptions.join('; ')}</DraftFlag> : null}
                      {item.review_state === 'accepted' ? (
                        <p className="faint small">
                          Now <IdTag id={item.display_id} to={`${base}/requirements/${item.number}`} />
                        </p>
                      ) : item.review_state === 'draft' && canReview ? (
                        <DraftActions mode={mode} setMode={setMode} decide={review.decide} busy={act.isPending} />
                      ) : null}
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
