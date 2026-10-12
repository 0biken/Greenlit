import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { ApiError } from '../../api/client'
import { serverMessage, usePlan, usePlanAction, usePlanVersion, type PlanAction } from '../../api/queries'
import type { PlanDetail } from '../../api/records'
import { Button } from '../../design/Button'
import { IdTag } from '../../design/IdTag'
import { Dialog } from '../../design/overlays'
import { ErrorState, SkeletonRows } from '../../design/states'
import { StatusChip } from '../../design/StatusChip'
import { SEVERITY_WORD as PRIORITY_WORD } from '../defects/DefectsList'
import { NotFound } from '../NotFound'
import { ProjectNav } from '../projects/ProjectNav'
import { CaseView } from './CaseView'
import '../defects/defects.css'
import './plans.css'

// One plan (M3-10): the cases of the version being looked at, the version history, the draft
// and what can be done with it, and the requirements no case covers yet (FR-PLAN-06).

const when = (iso: string) =>
  new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

export function PlanPage() {
  const { projectKey = '', no = '' } = useParams()
  const plan = usePlan(projectKey.toUpperCase(), no)

  if (plan.error instanceof ApiError && plan.error.isNotFound) return <NotFound />
  if (plan.isPending) return <SkeletonRows rows={6} />
  if (plan.isError) return <ErrorState message="Couldn't load this plan." onRetry={() => plan.refetch()} />
  return <PlanRecord projectKey={projectKey} plan={plan.data} />
}

function PlanRecord({ projectKey, plan }: { projectKey: string; plan: PlanDetail }) {
  const key = projectKey.toUpperCase()
  const base = `/${projectKey.toLowerCase()}`
  const here = `${base}/plans/${plan.number}`
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const act = usePlanAction(key, String(plan.number))
  const [confirm, setConfirm] = useState<null | { title: string; body: string; label: string; action: PlanAction }>(null)
  const [major, setMajor] = useState(false)

  // Which version's cases are shown: the one asked for, else the current one, else the draft.
  const asked = params.get('v')
  const shown = asked ?? plan.version ?? 'draft'
  const version = usePlanVersion(key, String(plan.number), shown)
  const previous = plan.versions.find((v) => v.number !== plan.version && v.state === 'superseded')

  function run(action: PlanAction, then?: () => void) {
    act.mutate(action, {
      onSuccess: () => {
        setConfirm(null)
        setParams({}, { replace: true })
        then?.()
      },
    })
  }

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
          </p>
          <h1 className="page-title defect-heading">
            <IdTag id={plan.display_id} /> {plan.title}{' '}
            {plan.version ? <span className="plan-version mono">v{plan.version}</span> : null}
          </h1>
          {plan.scope ? <p className="page-sub">{plan.scope}</p> : null}
        </div>
        {plan.actions.edit && !plan.draft ? (
          <Button
            variant="primary"
            disabled={act.isPending}
            onClick={() => run({ do: 'open' }, () => navigate(`${here}/edit`))}
          >
            Edit plan
          </Button>
        ) : null}
      </header>
      <ProjectNav projectKey={projectKey} />

      {act.isError ? (
        <p className="field-error" role="alert">
          {serverMessage(act.error) ?? "That didn't work. Try again."}
        </p>
      ) : null}

      {plan.draft ? (
        <section className="draft-bar" aria-label="Draft">
          <div>
            <StatusChip status="draft" word={plan.draft.submitted_at ? 'Draft, awaiting approval' : 'Draft open'} />{' '}
            <span>
              {plan.draft.cases} {plan.draft.cases === 1 ? 'case' : 'cases'}
              {plan.draft.submitted_at
                ? `, submitted by ${plan.draft.submitted_by ?? 'someone'} on ${when(plan.draft.submitted_at)}`
                : plan.version
                  ? `. Version ${plan.version} stays in use until this is approved.`
                  : '. Runs can start once it is approved.'}
            </span>
          </div>
          <div className="draft-bar-actions">
            {plan.version ? (
              <Link className="btn btn-quiet btn-sm" to={`${here}/diff?from=${plan.version}&to=draft`}>
                See changes
              </Link>
            ) : null}
            {plan.actions.edit ? (
              <>
                <Link className="btn btn-secondary btn-sm" to={`${here}/edit`}>
                  Edit draft
                </Link>
                {!plan.draft.submitted_at ? (
                  <Button size="sm" disabled={act.isPending || !plan.draft.cases} onClick={() => run({ do: 'submit' })}>
                    Submit for approval
                  </Button>
                ) : null}
              </>
            ) : null}
            {plan.actions.approve ? (
              <Button
                size="sm"
                variant="primary"
                disabled={act.isPending || !plan.draft.cases}
                onClick={() =>
                  setConfirm({
                    title: 'Approve this draft',
                    body: plan.version
                      ? `It becomes the plan's current version and replaces version ${plan.version}. New runs use it; runs already started keep the version they began with.`
                      : 'It becomes version 1.0, and runs can be started from it.',
                    label: 'Approve',
                    action: { do: 'approve', major: false },
                  })
                }
              >
                Approve
              </Button>
            ) : null}
            {plan.actions.edit ? (
              <Button
                size="sm"
                variant="danger"
                disabled={act.isPending}
                onClick={() =>
                  setConfirm({
                    title: 'Discard this draft',
                    body: plan.version
                      ? `Every change made in the draft is lost. Version ${plan.version} is not affected.`
                      : 'Every case in the draft is lost.',
                    label: 'Discard draft',
                    action: { do: 'discard' },
                  })
                }
              >
                Discard
              </Button>
            ) : null}
          </div>
        </section>
      ) : null}

      <div className="defect-layout">
        <div className="defect-record">
          <h2 className="dash-h">
            {shown === 'draft' ? 'Cases in the draft' : `Cases in version ${shown}`}
            {asked && asked !== plan.version ? (
              <>
                {' '}
                <button type="button" className="link-button small" onClick={() => setParams({}, { replace: true })}>
                  Back to the current version
                </button>
              </>
            ) : null}
          </h2>
          {version.isPending ? (
            <SkeletonRows rows={4} />
          ) : version.isError ? (
            <ErrorState message="Couldn't load the cases." onRetry={() => version.refetch()} />
          ) : !version.data.cases.length ? (
            <p className="faint">
              No cases yet. {plan.actions.edit && plan.draft ? <Link to={`${here}/edit`}>Add the first one</Link> : null}
            </p>
          ) : (
            <ol className="case-list">
              {version.data.cases.map((c) => (
                <li key={c.case}>
                  <CaseView item={c} base={base} />
                </li>
              ))}
            </ol>
          )}
        </div>

        <aside className="defect-side">
          <h2 className="dash-h">Versions</h2>
          {plan.versions.length ? (
            <ul className="plain-list version-list">
              {plan.versions.map((v) => (
                <li key={v.number}>
                  <button
                    type="button"
                    className="link-button mono"
                    aria-current={shown === v.number ? 'true' : undefined}
                    onClick={() => setParams(v.number === plan.version ? {} : { v: v.number }, { replace: true })}
                  >
                    v{v.number}
                  </button>
                  <span className="faint small">
                    {v.state === 'published' ? 'Current' : 'Superseded'} · {v.cases} {v.cases === 1 ? 'case' : 'cases'}
                    {v.approved_at ? ` · ${v.approved_by ?? 'Approved'} ${when(v.approved_at)}` : ''}
                  </span>
                  {v.state === 'superseded' && plan.actions.approve && !plan.draft ? (
                    <button
                      type="button"
                      className="link-button small"
                      onClick={() =>
                        setConfirm({
                          title: `Roll back to version ${v.number}`,
                          body: `This publishes a new version with the same cases as version ${v.number}. Nothing is deleted: version ${plan.version} stays in the history.`,
                          label: 'Roll back',
                          action: { do: 'roll_back', version: v.number },
                        })
                      }
                    >
                      Roll back
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="faint">Not approved yet.</p>
          )}
          {plan.version && previous ? (
            <p>
              <Link to={`${here}/diff?from=${previous.number}&to=${plan.version}`}>
                Compare v{previous.number} with v{plan.version}
              </Link>
            </p>
          ) : null}

          <h2 className="dash-h">Requirements with no test cases</h2>
          {plan.uncovered.length ? (
            <ul className="plain-list">
              {plan.uncovered.map((u) => (
                <li key={u.display_id} className="link-row">
                  <IdTag id={u.display_id} to={`${base}/requirements/${Number(u.display_id.split('-')[1])}`} />
                  <span className="link-row-title">{u.title}</span>
                  <span className="faint small">{PRIORITY_WORD[u.priority]}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="faint">Every accepted requirement on this project has a case.</p>
          )}
        </aside>
      </div>

      <Dialog
        open={confirm !== null}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={confirm?.title ?? ''}
        description={confirm?.body}
      >
        {confirm?.action.do === 'approve' && plan.version ? (
          <label className="check-row">
            <input type="checkbox" checked={major} onChange={(e) => setMajor(e.target.checked)} />
            <span>This is a major change: number it {Number(plan.version.split('.')[0]) + 1}.0</span>
          </label>
        ) : null}
        <div className="dialog-actions">
          <Button variant="quiet" onClick={() => setConfirm(null)}>
            Cancel
          </Button>
          <Button
            variant={confirm?.action.do === 'discard' ? 'danger' : 'primary'}
            disabled={act.isPending}
            onClick={() => {
              if (!confirm) return
              run(confirm.action.do === 'approve' ? { do: 'approve', major } : confirm.action)
            }}
          >
            {act.isPending ? 'Working…' : confirm?.label}
          </Button>
        </div>
      </Dialog>
    </div>
  )
}
