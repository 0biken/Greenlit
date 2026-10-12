import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { serverMessage, useDecideDefect, useDefect, useSetDefectStatus } from '../../api/queries'
import type { DefectDetail, TrackerStatus } from '../../api/records'
import { Button } from '../../design/Button'
import { IdTag } from '../../design/IdTag'
import { Mark } from '../../design/Mark'
import { Dialog, DialogClose } from '../../design/overlays'
import { ErrorState, SkeletonRows } from '../../design/states'
import { StatusChip } from '../../design/StatusChip'
import { NotFound } from '../NotFound'
import { ProjectNav } from '../projects/ProjectNav'
import { SEVERITY_WORD } from './DefectsList'
import { EvidenceList } from './EvidenceList'
import { RetestDialog } from './RetestDialog'
import './defects.css'

// Defect detail (M5-09, UX Flow 2). The record on the left; on the right what can be done
// now, then the retests and the history. Only actions this person may take are offered.

const STATUS_ACTION: Record<TrackerStatus, string> = {
  open: 'Reopen',
  in_progress: 'Start work',
  fixed: 'Mark fixed',
  closed: 'Close',
}

const when = (iso: string) =>
  new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

export function DefectDetailPage() {
  const { projectKey = '', no = '' } = useParams()
  const key = projectKey.toUpperCase()
  const defect = useDefect(key, no)
  const [retesting, setRetesting] = useState(false)
  const [deciding, setDeciding] = useState(false)
  const base = `/${projectKey.toLowerCase()}`

  if (defect.error instanceof ApiError && defect.error.isNotFound) return <NotFound />
  if (defect.isPending) {
    return (
      <div>
        <header className="page-head">
          <h1 className="page-title">BUG-{no}</h1>
        </header>
        <SkeletonRows rows={5} />
      </div>
    )
  }
  if (defect.isError) return <ErrorState message="Couldn't load this defect." onRetry={() => defect.refetch()} />

  const d = defect.data
  return (
    <div className="defect">
      <header className="page-head">
        <div>
          <p className="crumbs">
            <Link to={base} className="mono">
              {key}
            </Link>
            <span aria-hidden="true">/</span>
            <Link to={`${base}/bugs`}>Defects</Link>
          </p>
          <h1 className="page-title defect-heading">
            <IdTag id={d.display_id} /> {d.title}
          </h1>
          <p className="page-sub defect-facts">
            <StatusChip status={d.chip} word={d.shown_as} />
            <span>{SEVERITY_WORD[d.severity]} severity</span>
            <span>{d.owner_name ? `Owner: ${d.owner_name}` : 'No owner'}</span>
            {d.release ? (
              <span>
                Release{' '}
                <Link to={`${base}/releases/${d.release}`} className="mono">
                  {d.release}
                </Link>
              </span>
            ) : null}
          </p>
        </div>
      </header>
      <ProjectNav projectKey={projectKey} />

      <div className="defect-layout">
        <section className="defect-record" aria-label="The defect">
          <Field label="Steps to reproduce" text={d.steps} />
          <Field label="Expected" text={d.expected} />
          <Field label="Actual" text={d.actual} />

          <h2 className="overline dash-h">Evidence</h2>
          <EvidenceList files={d.evidence} />

          {d.found_in ? (
            <>
              <h2 className="overline dash-h">Where it was found</h2>
              <p className="found-in">
                <IdTag id={d.found_in.run} to={`${base}/runs/${d.found_in.run_no}`} /> <IdTag id={d.found_in.case} to={`${base}/cases/${Number(d.found_in.case.split('-')[1])}`} />{' '}
                {d.found_in.case_title}
              </p>
              {d.requirements.length ? (
                <ul className="plain-list">
                  {d.requirements.map((r) => (
                    <li key={r.display_id}>
                      <IdTag id={r.display_id} to={`${base}/requirements/${Number(r.display_id.split('-')[1])}`} /> {r.title}
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : null}

          {d.decision ? (
            <>
              <h2 className="overline dash-h">Decision</h2>
              <p className="sign-reason">
                <span className="overline">
                  {d.decision.decision === 'wont_fix' ? "Won't fix" : 'Deferred'}
                  {d.decision.by ? `, approved by ${d.decision.by}` : ''}
                </span>
                {d.decision.reason}
              </p>
            </>
          ) : null}
        </section>

        <aside className="defect-side">
          <Actions
            projectKey={key}
            defect={d}
            onRetest={() => setRetesting(true)}
            onDecide={() => setDeciding(true)}
          />

          <h2 className="overline dash-h">Retests</h2>
          {d.retests.length ? (
            <ol className="retest-list">
              {d.retests.map((r) => (
                <li key={r.id}>
                  <div className="retest-head">
                    <Mark kind={r.outcome === 'passed' ? 'pass' : 'fail'} />
                    <strong>{r.outcome === 'passed' ? 'Passed' : 'Failed'}</strong>
                    <span className="faint">
                      {r.by ?? 'Someone'}, {when(r.at)}
                    </span>
                  </div>
                  <EvidenceList files={r.evidence} />
                </li>
              ))}
            </ol>
          ) : (
            <p className="faint small">
              {d.tracker_status === 'fixed' || d.tracker_status === 'closed'
                ? 'Not retested yet.'
                : 'Nothing to retest until it is marked fixed.'}
            </p>
          )}

          <h2 className="overline dash-h">History</h2>
          <ol className="history-list">
            {d.history.map((h, i) => (
              <li key={i}>
                <time className="mono faint" dateTime={h.at}>
                  {when(h.at)}
                </time>
                <span>
                  <strong>{h.actor}</strong> {h.text}
                </span>
              </li>
            ))}
          </ol>
        </aside>
      </div>

      <RetestDialog
        defect={retesting ? { projectKey: key, displayId: d.display_id, title: d.title } : null}
        onClose={() => setRetesting(false)}
      />
      <DecisionDialog projectKey={key} defect={d} open={deciding} onOpenChange={setDeciding} />
    </div>
  )
}

function Field({ label, text }: { label: string; text: string }) {
  return (
    <div className="defect-field">
      <h2 className="overline">{label}</h2>
      {text ? <p className="pre">{text}</p> : <p className="faint">Not given.</p>}
    </div>
  )
}

function Actions({
  projectKey,
  defect,
  onRetest,
  onDecide,
}: {
  projectKey: string
  defect: DefectDetail
  onRetest: () => void
  onDecide: () => void
}) {
  const setStatus = useSetDefectStatus(projectKey, defect.display_id)
  const a = defect.actions
  // One primary action (UX rule 5): retest when there is a fix to check, otherwise mark fixed.
  const next: TrackerStatus | null = !a.retest && a.set_status.includes('fixed') ? 'fixed' : null
  const others = a.set_status.filter((s) => s !== next)
  if (!a.retest && !a.decide && !a.set_status.length) return null
  return (
    <div className="defect-actions">
      <div className="defect-actions-row">
        {a.retest ? (
          <Button variant="primary" onClick={onRetest}>
            Retest
          </Button>
        ) : null}
        {next ? (
          <Button variant="primary" disabled={setStatus.isPending} onClick={() => setStatus.mutate(next)}>
            {STATUS_ACTION[next]}
          </Button>
        ) : null}
        {others.map((s) => (
          <Button key={s} disabled={setStatus.isPending} onClick={() => setStatus.mutate(s)}>
            {STATUS_ACTION[s]}
          </Button>
        ))}
        {a.decide ? (
          <Button variant="quiet" onClick={onDecide}>
            Won't fix or defer
          </Button>
        ) : null}
      </div>
      {setStatus.isError ? (
        <p className="field-error" role="alert">
          {serverMessage(setStatus.error) ?? "Couldn't change the status. Try again."}
        </p>
      ) : null}
    </div>
  )
}

function DecisionDialog({
  projectKey,
  defect,
  open,
  onOpenChange,
}: {
  projectKey: string
  defect: DefectDetail
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const decide = useDecideDefect(projectKey, defect.display_id)
  const [decision, setDecision] = useState<'wont_fix' | 'deferred'>('deferred')
  const [reason, setReason] = useState('')

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!reason.trim()) return
    try {
      await decide.mutateAsync({ decision, reason: reason.trim() })
    } catch {
      return
    }
    setReason('')
    onOpenChange(false)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) decide.reset()
        onOpenChange(o)
      }}
      title={`Decide ${defect.display_id}`}
      description="The reason and your name stay on the record. It stops counting as open work."
    >
      <form onSubmit={submit} className="dialog-form">
        <fieldset className="segmented">
          <legend className="field-label">Decision</legend>
          {(
            [
              ['deferred', 'Deferred'],
              ['wont_fix', "Won't fix"],
            ] as const
          ).map(([value, label]) => (
            <label key={value} className="segment">
              <input type="radio" name="decision" checked={decision === value} onChange={() => setDecision(value)} />
              <span>{label}</span>
            </label>
          ))}
        </fieldset>
        <div className="field">
          <label className="field-label" htmlFor="decision-reason">
            Reason
          </label>
          <textarea
            id="decision-reason"
            className="textarea"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="The client moved this to release 2.5."
            required
          />
        </div>
        {decide.isError ? (
          <p className="field-error" role="alert">
            {serverMessage(decide.error) ?? "Couldn't save the decision. Try again."}
          </p>
        ) : null}
        <div className="dialog-actions">
          <DialogClose asChild>
            <Button variant="quiet">Cancel</Button>
          </DialogClose>
          <Button type="submit" variant="primary" disabled={!reason.trim() || decide.isPending}>
            {decide.isPending ? 'Saving…' : decision === 'deferred' ? 'Mark deferred' : "Mark won't fix"}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
