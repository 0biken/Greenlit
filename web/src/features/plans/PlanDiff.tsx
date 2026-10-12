import { Link, useParams, useSearchParams } from 'react-router'
import { ApiError } from '../../api/client'
import { usePlan, usePlanDiff } from '../../api/queries'
import type { PlanDiff as Diff } from '../../api/records'
import { IdTag } from '../../design/IdTag'
import { ErrorState, SkeletonRows } from '../../design/states'
import { NotFound } from '../NotFound'
import { ProjectNav } from '../projects/ProjectNav'
import '../defects/defects.css'
import './plans.css'

// Compare two versions of a plan (M3-06, FR-TC-03): cases added, removed and changed, down to
// the step. Every change carries a word as well as a colour.

const FIELD = { title: 'Title', preconditions: 'Before you start', expected: 'Expected result', priority: 'Priority' }
const STEP_WORD = { same: '', added: 'Added', removed: 'Removed', moved: 'Moved' }
const name = (v: string) => (v === 'draft' ? 'the draft' : `v${v}`)

export function PlanDiff() {
  const { projectKey = '', no = '' } = useParams()
  const key = projectKey.toUpperCase()
  const base = `/${projectKey.toLowerCase()}`
  const here = `${base}/plans/${no}`
  const [params, setParams] = useSearchParams()
  const plan = usePlan(key, no)
  const options = plan.data ? [...(plan.data.draft ? ['draft'] : []), ...plan.data.versions.map((v) => v.number)] : []
  const to = params.get('to') ?? options[0] ?? ''
  const from = params.get('from') ?? options.find((o) => o !== to) ?? ''
  const all = params.get('all') === '1'
  const diff = usePlanDiff(key, no, from, to, all)

  if (plan.error instanceof ApiError && plan.error.isNotFound) return <NotFound />
  if (plan.isPending) return <SkeletonRows rows={6} />
  if (plan.isError) return <ErrorState message="Couldn't load this plan." onRetry={() => plan.refetch()} />

  const set = (next: Record<string, string>) =>
    setParams({ from, to, ...(all ? { all: '1' } : {}), ...next }, { replace: true })

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
            <Link to={here}>{plan.data.display_id}</Link>
          </p>
          <h1 className="page-title defect-heading">What changed in {plan.data.title}</h1>
        </div>
      </header>
      <ProjectNav projectKey={projectKey} />

      {options.length < 2 ? (
        <p className="faint">
          This plan has only one version, so there is nothing to compare yet. <Link to={here}>Back to the plan</Link>
        </p>
      ) : (
        <>
          <div className="diff-pick">
            <label>
              <span className="field-label">From</span>
              <select className="input" value={from} onChange={(e) => set({ from: e.target.value })}>
                {options.map((o) => (
                  <option key={o} value={o}>
                    {o === 'draft' ? 'Draft' : `v${o}`}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className="field-label">To</span>
              <select className="input" value={to} onChange={(e) => set({ to: e.target.value })}>
                {options.map((o) => (
                  <option key={o} value={o}>
                    {o === 'draft' ? 'Draft' : `v${o}`}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {from === to ? (
            <p className="faint">Choose two different versions.</p>
          ) : diff.isPending ? (
            <SkeletonRows rows={5} />
          ) : diff.isError ? (
            <ErrorState message="Couldn't compare these versions." onRetry={() => diff.refetch()} />
          ) : (
            <DiffBody
              diff={diff.data}
              base={base}
              from={from}
              to={to}
              showAll={all}
              onToggle={() => set({ all: all ? '' : '1' })}
            />
          )}
        </>
      )}
    </div>
  )
}

function DiffBody({
  diff,
  base,
  from,
  to,
  showAll,
  onToggle,
}: {
  diff: Diff
  base: string
  from: string
  to: string
  showAll: boolean
  onToggle: () => void
}) {
  const nothing = !diff.added.length && !diff.removed.length && !diff.changed.length
  const count = (n: number, word: string) => `${n} ${word}`
  return (
    <div className="diff">
      <p className="diff-summary">
        From {name(from)} to {name(to)}: {count(diff.added.length, 'added')}, {count(diff.removed.length, 'removed')},{' '}
        {count(diff.changed.length, 'changed')}, {count(diff.unchanged_count, 'unchanged')}.
      </p>
      {nothing ? <p className="faint">These two versions have the same cases.</p> : null}

      {diff.added.length ? (
        <section>
          <h2 className="dash-h">Added</h2>
          <ul className="plain-list">
            {diff.added.map((c) => (
              <li key={c.case} className="diff-line diff-added">
                <span className="diff-word">Added</span>
                <IdTag id={c.case} to={`${base}/cases/${c.number}`} /> {c.title}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {diff.removed.length ? (
        <section>
          <h2 className="dash-h">Removed</h2>
          <ul className="plain-list">
            {diff.removed.map((c) => (
              <li key={c.case} className="diff-line diff-removed">
                <span className="diff-word">Removed</span>
                <IdTag id={c.case} to={`${base}/cases/${c.number}`} /> {c.title}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {diff.changed.length ? (
        <section>
          <h2 className="dash-h">Changed</h2>
          {diff.changed.map((c) => (
            <article key={c.case} className="diff-case">
              <h3 className="diff-case-head">
                <IdTag id={c.case} to={`${base}/cases/${c.number}`} /> {c.title}
              </h3>
              {c.changes.map((f) => (
                <dl key={f.field} className="diff-field">
                  <dt className="overline">{FIELD[f.field]}</dt>
                  <dd className="diff-line diff-removed">
                    <span className="diff-word">Was</span>
                    <span className="pre">{f.before || 'Empty'}</span>
                  </dd>
                  <dd className="diff-line diff-added">
                    <span className="diff-word">Now</span>
                    <span className="pre">{f.after || 'Empty'}</span>
                  </dd>
                </dl>
              ))}
              {c.steps.length ? (
                <>
                  <p className="overline">Steps</p>
                  <ol className="diff-steps">
                    {c.steps.map((s, i) => (
                      <li key={i} className={`diff-line diff-${s.op}`}>
                        <span className="diff-no mono">{s.after ?? '–'}</span>
                        <span className="diff-word">
                          {s.op === 'moved' ? `Moved from ${s.before}` : STEP_WORD[s.op]}
                        </span>
                        <span>{s.text}</span>
                      </li>
                    ))}
                  </ol>
                </>
              ) : null}
            </article>
          ))}
        </section>
      ) : null}

      {diff.unchanged_count ? (
        <section>
          <button type="button" className="link-button" onClick={onToggle}>
            {showAll ? 'Hide' : 'Show'} the {diff.unchanged_count} unchanged
          </button>
          {showAll ? (
            <ul className="plain-list">
              {diff.unchanged.map((c) => (
                <li key={c.case} className="diff-line">
                  <IdTag id={c.case} to={`${base}/cases/${c.number}`} /> {c.title}
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
    </div>
  )
}
