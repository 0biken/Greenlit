import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { serverMessage, usePlans, useReleases, useRuns, useStartRun } from '../../api/queries'
import { useOrg } from '../../app/Gate'
import { Button } from '../../design/Button'
import { IdTag } from '../../design/IdTag'
import { Mark } from '../../design/Mark'
import { Dialog, DialogClose } from '../../design/overlays'
import { EmptyState, ErrorState, SkeletonRows } from '../../design/states'
import { ProjectNav } from '../projects/ProjectNav'
import '../defects/defects.css'
import './runs.css'

// Test runs (UX screen 9): newest first, each with its plan version, release and counts.

const CAN_TEST = ['owner', 'admin', 'qa_lead', 'qa_engineer']

export function RunsList() {
  const { projectKey = '' } = useParams()
  const key = projectKey.toUpperCase()
  const { membership } = useOrg()
  const runs = useRuns(key)
  const [starting, setStarting] = useState(false)
  const base = `/${projectKey.toLowerCase()}`
  const canTest = CAN_TEST.includes(membership.role)

  return (
    <div>
      <header className="page-head">
        <div>
          <p className="crumbs">
            <Link to="/projects">Projects</Link>
            <span aria-hidden="true">/</span>
            <span className="mono">{key}</span>
          </p>
          <h1 className="page-title">Runs</h1>
        </div>
        {canTest ? (
          <Button variant="primary" onClick={() => setStarting(true)}>
            Start a run
          </Button>
        ) : null}
      </header>
      <ProjectNav projectKey={projectKey} />

      {runs.isPending ? (
        <SkeletonRows rows={5} />
      ) : runs.isError ? (
        <ErrorState message="Couldn't load the runs." onRetry={() => runs.refetch()} />
      ) : !runs.data.length ? (
        <EmptyState
          title="No runs yet."
          actions={canTest ? <Button onClick={() => setStarting(true)}>Start a run</Button> : undefined}
        >
          A run records the result of every case in one version of a plan, for one release.
        </EmptyState>
      ) : (
        <ul className="ledger defect-list">
          {runs.data.map((r) => (
            <li key={r.display_id} className="ledger-row">
              <span className="ledger-margin">
                <span>{r.total ? `${r.passed}/${r.total}` : '0'}</span>
                <Mark kind={r.failed ? 'fail' : r.state === 'complete' ? 'pass' : 'open'} />
              </span>
              <Link to={`${base}/runs/${r.number}`} className="ledger-body defect-row">
                <span className="defect-main">
                  <IdTag id={r.display_id} />
                  <span className="defect-title">
                    {r.plan} <span className="mono faint">v{r.plan_version}</span>
                  </span>
                </span>
                <span className="defect-meta">
                  <span className="mono">{r.release}</span>
                  {r.build ? <span className="mono">{r.build}</span> : null}
                  {r.environment ? <span>{r.environment}</span> : null}
                  <span>
                    {r.failed} failed, {r.blocked} blocked, {r.not_run} not run
                  </span>
                </span>
                <span className="defect-status">
                  <span className={`chip ${r.state === 'complete' ? 'chip-ver' : 'chip-open'}`}>
                    {r.state === 'complete' ? 'Complete' : 'In progress'}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <StartRunDialog projectKey={key} open={starting} onOpenChange={setStarting} />
    </div>
  )
}

function StartRunDialog({
  projectKey,
  open,
  onOpenChange,
}: {
  projectKey: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const navigate = useNavigate()
  const plans = usePlans(projectKey, open)
  const releases = useReleases(projectKey)
  const start = useStartRun(projectKey)
  const openReleases = releases.data?.filter((r) => r.state === 'open') ?? []

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    try {
      const run = await start.mutateAsync({
        plan: Number(form.get('plan')),
        release: String(form.get('release')),
        build: String(form.get('build') ?? '').trim(),
        environment: String(form.get('environment') ?? '').trim(),
      })
      onOpenChange(false)
      navigate(`/${projectKey.toLowerCase()}/runs/${run.number}`)
    } catch {
      // shown from start.error
    }
  }

  const nothingToRun = plans.data && !plans.data.length
  const noRelease = releases.data && !openReleases.length
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) start.reset()
        onOpenChange(o)
      }}
      title="Start a run"
      description="The run is tied to the plan's current version for life, so later edits to the plan don't change it."
    >
      {nothingToRun ? (
        <p className="dialog-form faint">No plan has an approved version yet, so there is nothing to run.</p>
      ) : noRelease ? (
        <p className="dialog-form faint">
          There is no open release. <Link to={`/${projectKey.toLowerCase()}/releases`}>Create one first.</Link>
        </p>
      ) : (
        <form onSubmit={submit} className="dialog-form">
          <div className="field">
            <label className="field-label" htmlFor="run-plan">
              Plan
            </label>
            <select className="input" id="run-plan" name="plan" required>
              {plans.data?.map((p) => (
                <option key={p.number} value={p.number}>
                  {p.display_id} {p.title} (v{p.version}, {p.cases} {p.cases === 1 ? 'case' : 'cases'})
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="run-release">
              Release
            </label>
            <select className="input" id="run-release" name="release" required>
              {openReleases.map((r) => (
                <option key={r.version} value={r.version}>
                  {r.version}
                </option>
              ))}
            </select>
          </div>
          <div className="form-pair">
            <div className="field">
              <label className="field-label" htmlFor="run-build">
                Build
              </label>
              <input className="input" id="run-build" name="build" maxLength={100} placeholder="2.4.1-rc2" />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="run-env">
                Environment
              </label>
              <input className="input" id="run-env" name="environment" maxLength={100} placeholder="staging" />
            </div>
          </div>
          {start.isError ? (
            <p className="field-error" role="alert">
              {serverMessage(start.error) ?? "Couldn't start the run. Try again."}
            </p>
          ) : null}
          <div className="dialog-actions">
            <DialogClose asChild>
              <Button variant="quiet">Cancel</Button>
            </DialogClose>
            <Button type="submit" variant="primary" disabled={start.isPending || plans.isPending}>
              {start.isPending ? 'Starting…' : 'Start run'}
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  )
}
