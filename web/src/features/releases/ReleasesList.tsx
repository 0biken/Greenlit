import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { serverMessage, useCreateRelease, useReleases } from '../../api/queries'
import { useOrg } from '../../app/Gate'
import { Button } from '../../design/Button'
import { Dialog, DialogClose } from '../../design/overlays'
import { EmptyState, ErrorState, SkeletonRows } from '../../design/states'
import { ProjectNav } from '../projects/ProjectNav'
import '../defects/defects.css'

// Releases (UX screen 11): each opens its readiness, report and sign-off.

const CAN_TEST = ['owner', 'admin', 'qa_lead', 'qa_engineer']
const STATE = { open: 'Open', signed_off: 'Signed off', cancelled: 'Cancelled' } as const

export function ReleasesList() {
  const { projectKey = '' } = useParams()
  const key = projectKey.toUpperCase()
  const { membership } = useOrg()
  const releases = useReleases(key)
  const [creating, setCreating] = useState(false)
  const base = `/${projectKey.toLowerCase()}`
  const canCreate = CAN_TEST.includes(membership.role)

  return (
    <div>
      <header className="page-head">
        <div>
          <p className="crumbs">
            <Link to="/projects">Projects</Link>
            <span aria-hidden="true">/</span>
            <span className="mono">{key}</span>
          </p>
          <h1 className="page-title">Releases</h1>
        </div>
        {canCreate ? (
          <Button variant="primary" onClick={() => setCreating(true)}>
            Create a release
          </Button>
        ) : null}
      </header>
      <ProjectNav projectKey={projectKey} />

      {releases.isPending ? (
        <SkeletonRows rows={3} />
      ) : releases.isError ? (
        <ErrorState message="Couldn't load the releases." onRetry={() => releases.refetch()} />
      ) : !releases.data.length ? (
        <EmptyState title="No releases yet.">
          A release groups the runs, defects and report for one version you plan to ship.
        </EmptyState>
      ) : (
        <ul className="ledger defect-list">
          {releases.data.map((r) => (
            <li key={r.version} className="ledger-row">
              <span className="ledger-margin">
                {r.runs} {r.runs === 1 ? 'run' : 'runs'}
              </span>
              <Link to={`${base}/releases/${r.version}`} className="ledger-body defect-row">
                <span className="defect-main">
                  <span className="defect-title mono">{r.version}</span>
                </span>
                <span className="defect-meta">
                  {r.due ? (
                    <span>
                      Due{' '}
                      {new Date(r.due).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}
                    </span>
                  ) : (
                    <span>No date set</span>
                  )}
                </span>
                <span className="defect-status">
                  <span className={`chip ${r.state === 'signed_off' ? 'chip-ver' : 'chip-open'}`}>{STATE[r.state]}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <CreateReleaseDialog projectKey={key} open={creating} onOpenChange={setCreating} />
    </div>
  )
}

function CreateReleaseDialog({
  projectKey,
  open,
  onOpenChange,
}: {
  projectKey: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const create = useCreateRelease(projectKey)

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    try {
      await create.mutateAsync({
        version: String(form.get('version')).trim(),
        due: String(form.get('due') ?? '') || null,
      })
      onOpenChange(false)
    } catch {
      // shown from create.error
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) create.reset()
        onOpenChange(o)
      }}
      title="Create a release"
    >
      <form onSubmit={submit} className="dialog-form">
        <div className="form-pair">
          <div className="field">
            <label className="field-label" htmlFor="release-version">
              Version
            </label>
            <input className="input" id="release-version" name="version" required maxLength={60} placeholder="2.5.0" />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="release-due">
              Target date
            </label>
            <input className="input" id="release-due" name="due" type="date" />
          </div>
        </div>
        {create.isError ? (
          <p className="field-error" role="alert">
            {serverMessage(create.error) ?? "Couldn't create the release. Try again."}
          </p>
        ) : null}
        <div className="dialog-actions">
          <DialogClose asChild>
            <Button variant="quiet">Cancel</Button>
          </DialogClose>
          <Button type="submit" variant="primary" disabled={create.isPending}>
            {create.isPending ? 'Creating…' : 'Create release'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
