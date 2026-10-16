import { Link, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { serverMessage, useCaseDrafts, useCaseReview } from '../../api/queries'
import type { CaseDraft, CaseDraftsDetail, PlanCase } from '../../api/records'
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
import { CaseForm } from './PlanEditor'
import '../defects/defects.css'
import './plans.css'

// Case drafts for one plan (M3-08, UX §7): the requirement a drafted case covers on the left,
// the drafted cases on the right. An accepted case joins the plan's draft; nothing a tester
// has not accepted is ever run.

const TYPE_WORD = { positive: 'Positive', negative: 'Negative', edge: 'Edge case', accessibility: 'Accessibility', '': '' }

export function CaseDrafts() {
  const { projectKey = '', no = '' } = useParams()
  const drafts = useCaseDrafts(projectKey.toUpperCase(), no)

  if (drafts.error instanceof ApiError && drafts.error.isNotFound) return <NotFound />
  if (drafts.isPending) return <SkeletonRows rows={6} />
  if (drafts.isError && !drafts.data) {
    return <ErrorState message="Couldn't load the drafted cases." onRetry={() => drafts.refetch()} />
  }
  return <Review projectKey={projectKey} data={drafts.data} />
}

/** A drafted case in the shape the plan's case form edits. */
const asCase = (d: CaseDraft): PlanCase => ({
  case: d.case,
  number: d.number,
  revision: 1,
  title: d.title,
  preconditions: d.preconditions,
  steps: d.steps,
  expected: d.expected,
  priority: d.priority,
  requirements: d.requirements.map((r) => ({ display_id: r.display_id, number: r.number, title: r.title, stale: false })),
  stale: false,
})

function Review({ projectKey, data }: { projectKey: string; data: CaseDraftsDetail }) {
  const key = projectKey.toUpperCase()
  const base = `/${projectKey.toLowerCase()}`
  const plan = `${base}/plans/${data.plan_no}`
  const act = useCaseReview(key, String(data.plan_no))
  const canReview = data.actions.review
  const review = useReviewCursor(data.items, {
    canReview,
    busy: act.isPending,
    onDecide: (item, decision, reason, viewed_ms, done) =>
      act.mutate({ do: 'decide', number: item.number, decision, reason, viewed_ms }, { onSuccess: done }),
  })
  const { current, waiting, mode, setMode } = review
  const busy = Boolean(data.job?.running)

  return (
    <div className="defect">
      <header className="page-head">
        <div>
          <p className="crumbs">
            <Link to={base} className="mono">
              {key}
            </Link>
            <span aria-hidden="true">/</span>
            <Link to={`${base}/plans`}>Test plans</Link>
            <span aria-hidden="true">/</span>
            <Link to={plan}>{data.plan}</Link>
          </p>
          <h1 className="page-title defect-heading">Drafted cases for {data.title}</h1>
          <p className="page-sub defect-facts">
            <span>{data.drafts} to review</span>
            <span>{data.accepted} accepted</span>
            <span>{data.rejected} rejected</span>
            {data.fast_accepts ? (
              <span className="fast-accepts">{data.fast_accepts} accepted in under 2 seconds each</span>
            ) : null}
          </p>
        </div>
        <Link className="btn btn-primary" to={plan}>
          Done
        </Link>
      </header>
      <ProjectNav projectKey={projectKey} />

      <ReviewNotes
        job={data.job}
        busyWord={busy ? data.job?.progress || 'Drafting cases' : null}
        allowance={data.allowance_message}
        leftOut={data.left_out}
        actionError={act.isError ? (serverMessage(act.error) ?? "That didn't work. Try again.") : null}
      />

      {!data.items.length && !busy ? (
        <p className="faint">
          No cases have been drafted for this plan. <Link to={plan}>Go back to the plan</Link> and choose Draft cases
          with AI, or add cases by hand.
        </p>
      ) : (
        <div className="review-layout">
          <section className="review-source" aria-label="Requirements this case covers">
            {current?.requirements.length ? (
              current.requirements.map((r) => (
                <article key={r.display_id} className="review-page">
                  <p className="case-view-head">
                    <IdTag id={r.display_id} to={`${base}/requirements/${r.number}`} />
                    <span className="case-view-title">{r.title}</span>
                  </p>
                  <p className="pre review-text">{r.text}</p>
                </article>
              ))
            ) : (
              <p className="faint">Choose a drafted case to see the requirement it covers.</p>
            )}
          </section>

          <section className="review-drafts" aria-label="Drafted cases">
            <GapsBox gaps={data.gaps} />
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

            <ol className="draft-cards">
              {data.items.map((item) => {
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
                        {[TYPE_WORD[item.case_type], PRIORITY_WORD[item.priority]].filter(Boolean).join(' · ')}
                      </span>
                    </button>
                    {on && mode === 'edit' ? (
                      <div className="draft-card-body">
                        <CaseForm
                          key={item.number}
                          projectKey={projectKey}
                          item={asCase(item)}
                          busy={act.isPending}
                          error={null}
                          saveLabel="Save draft"
                          onCancel={() => setMode('read')}
                          onSave={(body) =>
                            act.mutate({ do: 'edit', number: item.number, body }, { onSuccess: () => setMode('read') })
                          }
                        />
                      </div>
                    ) : on ? (
                      <div className="draft-card-body">
                        {item.preconditions ? (
                          <p className="muted">
                            <span className="overline">Before you start</span> {item.preconditions}
                          </p>
                        ) : null}
                        <ol className="case-steps">
                          {item.steps.map((step, i) => (
                            <li key={i}>{step}</li>
                          ))}
                        </ol>
                        <p className="case-expected">
                          <span className="overline">Expected</span>
                          {item.expected}
                        </p>
                        {item.possible_duplicate_of ? (
                          <DraftFlag>
                            Possible duplicate of{' '}
                            <IdTag
                              id={item.possible_duplicate_of}
                              to={`${base}/cases/${Number(item.possible_duplicate_of.split('-')[1])}`}
                            />
                          </DraftFlag>
                        ) : null}
                        {item.assumptions.length ? <DraftFlag>Assumes: {item.assumptions.join('; ')}</DraftFlag> : null}
                        {item.review_state === 'accepted' ? (
                          <p className="faint small">
                            Now <IdTag id={item.case} to={`${base}/cases/${item.number}`} /> in the{' '}
                            <Link to={`${plan}?v=draft`}>plan's draft</Link>
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
            {canReview && !busy && data.accepted ? (
              <p className="faint small">
                Accepted cases are in the <Link to={`${plan}?v=draft`}>plan's draft</Link>. Submit it for a lead to
                approve when you are done.
              </p>
            ) : null}
          </section>
        </div>
      )}
      {canReview && !data.items.length && !busy ? (
        <p>
          <Button onClick={() => act.mutate({ do: 'draft_cases' })} disabled={act.isPending || Boolean(data.allowance_message)}>
            Draft cases for requirements with no test cases
          </Button>
        </p>
      ) : null}
    </div>
  )
}
