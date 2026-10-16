import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { serverMessage, useCreatePlan, usePlans } from '../../api/queries'
import { useOrg } from '../../app/Gate'
import { Button } from '../../design/Button'
import { IdTag } from '../../design/IdTag'
import { Mark } from '../../design/Mark'
import { Dialog } from '../../design/overlays'
import { EmptyState, ErrorState, SkeletonRows } from '../../design/states'
import { StatusChip } from '../../design/StatusChip'
import { ProjectNav } from '../projects/ProjectNav'
import { CAN_WRITE } from '../requirements/RequirementsList'
import '../defects/defects.css'
import './plans.css'

// Test plans (M3-10): each plan with its current version and whether a draft is open.

export function PlansList() {
  const { projectKey = '' } = useParams()
  const key = projectKey.toUpperCase()
  const { membership } = useOrg()
  const plans = usePlans(key)
  const [adding, setAdding] = useState(false)
  const base = `/${projectKey.toLowerCase()}/plans`
  const canWrite = CAN_WRITE.includes(membership.role)

  return (
    <div>
      <header className="page-head">
        <div>
          <p className="crumbs">
            <Link to="/projects">Projects</Link>
            <span aria-hidden="true">/</span>
            <span className="mono">{key}</span>
          </p>
          <h1 className="page-title">Test plans</h1>
        </div>
        {canWrite ? (
          <Button variant="primary" onClick={() => setAdding(true)}>
            New plan
          </Button>
        ) : null}
      </header>
      <ProjectNav projectKey={projectKey} />

      {plans.isPending ? (
        <SkeletonRows rows={4} />
      ) : plans.isError && !plans.data ? (
        <ErrorState message="Couldn't load the plans." onRetry={() => plans.refetch()} />
      ) : !plans.data.length ? (
        <EmptyState
          title="No test plans on this project yet."
          actions={canWrite ? <Button onClick={() => setAdding(true)}>New plan</Button> : undefined}
        >
          A plan is a set of test cases for one area. Runs are started from its approved version.
        </EmptyState>
      ) : (
        <ul className="ledger defect-list">
          {plans.data.map((p) => (
            <li key={p.number} className="ledger-row">
              <span className="ledger-margin">
                <span>{p.version ? `v${p.version}` : ''}</span>
                <Mark kind={p.version ? 'verified' : 'draft'} />
              </span>
              <Link to={`${base}/${p.number}`} className="ledger-body defect-row">
                <span className="defect-main">
                  <IdTag id={p.display_id} />
                  <span className="defect-title">{p.title}</span>
                </span>
                <span className="defect-meta">
                  <span>
                    {p.cases} {p.cases === 1 ? 'case' : 'cases'}
                  </span>
                  {p.version ? <span>Approved</span> : <span>Not approved yet</span>}
                </span>
                <span className="defect-status">
                  {p.case_drafts ? (
                    <StatusChip
                      status="draft"
                      word={p.case_drafts === 1 ? '1 drafted case to review' : `${p.case_drafts} drafted cases to review`}
                    />
                  ) : p.has_draft ? (
                    <StatusChip status="draft" word={p.draft_submitted ? 'Draft, awaiting approval' : 'Draft open'} />
                  ) : null}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <NewPlanDialog projectKey={projectKey} open={adding} onOpenChange={setAdding} />
    </div>
  )
}

function NewPlanDialog({
  projectKey,
  open,
  onOpenChange,
}: {
  projectKey: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const navigate = useNavigate()
  const create = useCreatePlan(projectKey.toUpperCase())

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    create.mutate(
      { title: String(form.get('title') ?? '').trim(), scope: String(form.get('scope') ?? '').trim() },
      { onSuccess: (plan) => navigate(`/${projectKey.toLowerCase()}/plans/${plan.number}/edit`) },
    )
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="New plan"
      description="It starts as a draft. Add cases, then submit it for a lead to approve."
    >
      <form onSubmit={submit} className="dialog-form">
        <div className="field">
          <label className="field-label" htmlFor="plan-title">
            Title
          </label>
          <input className="input" id="plan-title" name="title" required maxLength={200} placeholder="Checkout" autoFocus />
          <span className="field-hint">Usually the area it covers. Release reports group results by it.</span>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="plan-scope">
            Scope <span className="faint">(optional)</span>
          </label>
          <textarea className="textarea" id="plan-scope" name="scope" rows={3} />
        </div>
        {create.isError ? (
          <p className="field-error" role="alert">
            {serverMessage(create.error) ?? "Couldn't create the plan. Try again."}
          </p>
        ) : null}
        <div className="dialog-actions">
          <Button variant="quiet" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={create.isPending}>
            {create.isPending ? 'Creating…' : 'Create plan'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
