import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import type { Blocker, BlockerType, ReleaseDetail } from '../../api/planned'
import { ApiError } from '../../api/client'
import { useRelease, useSignOff } from '../../api/queries'
import { useOrg } from '../../app/Gate'
import { Button } from '../../design/Button'
import { IdTag } from '../../design/IdTag'
import { Mark, type MarkKind } from '../../design/Mark'
import { Dialog, DialogClose } from '../../design/overlays'
import { ErrorState, SkeletonRows } from '../../design/states'
import { StatusChip } from '../../design/StatusChip'
import { RetestDialog } from '../defects/RetestDialog'
import { NotFound } from '../NotFound'
import { CoverageBlock, Linkified } from '../projects/ProjectHome'
import { ReadinessChip } from './ReadinessChip'
import './release.css'

// Release readiness and sign-off (UX Flow 3, wireframe §8, M8-09). Blockers on the left
// where the lead's eye lands first; the report and the one green button on the right.

const BLOCKER: Record<BlockerType, { label: string; mark: MarkKind }> = {
  closed_failed_retest: { label: 'Closed with a failed retest', mark: 'fail' },
  open_critical: { label: 'Open critical defects', mark: 'fail' },
  needs_retest: { label: 'Fixed but not retested', mark: 'hold' },
  unfiled_failure: { label: 'Failures without a defect', mark: 'fail' },
  uncovered_critical: { label: 'Critical requirements without tests', mark: 'open' },
}
const BLOCKER_ORDER: BlockerType[] = ['closed_failed_retest', 'open_critical', 'needs_retest', 'unfiled_failure', 'uncovered_critical']

const SIGN_OFF_ROLES = ['owner', 'admin', 'qa_lead']

export function ReleasePage() {
  const { projectKey = '', version = '' } = useParams()
  const key = projectKey.toUpperCase()
  const release = useRelease(key, version)
  const [retesting, setRetesting] = useState<Blocker | null>(null)

  if (release.error instanceof ApiError && release.error.isNotFound) return <NotFound />

  return (
    <div className="release">
      <header className="page-head">
        <div>
          <p className="crumbs">
            <Link to={`/${projectKey.toLowerCase()}`} className="mono">
              {key}
            </Link>
            <span aria-hidden="true">/</span>
            <span>Releases</span>
          </p>
          <h1 className="page-title">
            Release <span className="mono-title">{version}</span>
          </h1>
          {release.data?.due ? (
            <p className="page-sub">
              Due {new Date(release.data.due).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })}
            </p>
          ) : null}
        </div>
      </header>

      <div className="release-layout">
        <section className="readiness" aria-labelledby="readiness-h" aria-live="polite">
          <h2 id="readiness-h" className="sr-only">
            Readiness
          </h2>
          {release.isPending ? (
            <>
              <ReadinessChip readiness="checking" />
              <SkeletonRows rows={5} />
            </>
          ) : release.isError ? (
            <>
              <ReadinessChip readiness="unknown" />
              <ErrorState message="Couldn't check readiness. Sign-off is blocked until it can." onRetry={() => release.refetch()} />
            </>
          ) : (
            <ReadinessPanel release={release.data} onRetest={setRetesting} />
          )}
        </section>

        <section className="report" aria-labelledby="report-h">
          {release.data ? (
            <ReportPane release={release.data} />
          ) : (
            <div className="report-sheet">
              <h2 id="report-h" className="overline">
                Release report
              </h2>
              <SkeletonRows rows={4} />
            </div>
          )}
          <SignOffBox release={release.data} checking={release.isPending} failed={release.isError} />
        </section>
      </div>

      <RetestDialog
        defect={retesting ? { displayId: retesting.display_id, title: retesting.title } : null}
        onClose={() => setRetesting(null)}
      />
    </div>
  )
}

function ReadinessPanel({ release, onRetest }: { release: ReleaseDetail; onRetest: (b: Blocker) => void }) {
  // The tick draws itself only when the release turns Ready while you watch.
  const wasReady = useRef(release.readiness === 'ready')
  const [justTurnedReady, setJustTurnedReady] = useState(false)
  useEffect(() => {
    if (release.readiness === 'ready' && !wasReady.current) setJustTurnedReady(true)
    wasReady.current = release.readiness === 'ready'
  }, [release.readiness])

  const ready = release.readiness === 'ready'
  const n = release.blockers.length
  return (
    <>
      <div className="readiness-head">
        <ReadinessChip readiness={release.readiness} draw={justTurnedReady} />
        <p className="readiness-statement" key={n}>
          {ready ? (
            'Every blocker is resolved.'
          ) : (
            <>
              <span className="blocker-count">{n}</span> {n === 1 ? 'blocker needs' : 'blockers need'} work before this release
              can be signed off.
            </>
          )}
        </p>
      </div>

      <CoverageBlock coverage={release.coverage} />

      {BLOCKER_ORDER.map((type) => {
        const list = release.blockers.filter((b) => b.type === type)
        if (!list.length) return null
        const def = BLOCKER[type]
        return (
          <div key={type} className="blocker-group" role="group" aria-label={`${def.label}, ${list.length}`}>
            <div className="ledger-group">
              <h3 className="overline">
                {def.label} · {list.length}
              </h3>
            </div>
            <ul className="blocker-list">
              {list.map((b) => (
                <li key={b.display_id} className="ledger-row">
                  <span className="ledger-margin">
                    <span>{b.age_days === 0 ? 'new' : `${b.age_days}d`}</span>
                    <Mark kind={def.mark} />
                  </span>
                  <span className="ledger-body blocker-body">
                    <span className="blocker-main">
                      <IdTag id={b.display_id} to={blockerPath(release.project_key, b.display_id)} />
                      <span className="blocker-title">{b.title}</span>
                    </span>
                    {b.owner_name ? <span className="faint small">{b.owner_name}</span> : null}
                    {type === 'needs_retest' ? (
                      <Button size="sm" onClick={() => onRetest(b)}>
                        Retest
                      </Button>
                    ) : type === 'closed_failed_retest' ? (
                      <StatusChip status="retest_failed" />
                    ) : null}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </>
  )
}

function blockerPath(projectKey: string, displayId: string) {
  const [prefix, no] = displayId.split('-')
  return `/${projectKey.toLowerCase()}/${prefix === 'REQ' ? 'requirements' : 'bugs'}/${no}`
}

function ReportPane({ release }: { release: ReleaseDetail }) {
  const r = release.report
  return (
    <div className="report-sheet" data-frozen={r.state === 'signed' || undefined}>
      <div className="report-head">
        <h2 id="report-h" className="overline">
          Release report <IdTag id={r.display_id} />
        </h2>
        {r.state === 'draft' ? <StatusChip status="draft" /> : <StatusChip status="verified" detail="Signed" />}
      </div>
      <p className="report-summary">{r.summary}</p>
      {r.sections.map((sec) => (
        <div key={sec.heading} className="report-section">
          <h3>{sec.heading}</h3>
          <ul>
            {sec.lines.map((line, i) => (
              <li key={i}>
                <Linkified text={line.text} refs={line.refs} projectKey={release.project_key} />
                <span className="report-refs">
                  {line.refs
                    .filter((ref) => !line.text.includes(ref))
                    .map((ref) => (
                      <IdTag key={ref} id={ref} />
                    ))}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {r.state === 'draft' ? (
        <p className="report-note faint">Draft. Every claim links to the run or defect it came from. Edit before signing off.</p>
      ) : null}
    </div>
  )
}

function SignOffBox({ release, checking, failed }: { release?: ReleaseDetail; checking: boolean; failed: boolean }) {
  const { membership } = useOrg()
  const [open, setOpen] = useState(false)
  const canSign = SIGN_OFF_ROLES.includes(membership.role)

  if (release?.sign_off) {
    const s = release.sign_off
    return (
      <div className="sign-box signed">
        <div className="sign-line">
          <div>
            <span className="sign-name">{s.by}</span>
            <span className="overline">Signed off by</span>
          </div>
          <div>
            <span className="sign-name mono">
              {new Date(s.at).toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
            </span>
            <span className="overline">Date</span>
          </div>
        </div>
        <p className="sign-readiness">
          Readiness at sign-off: <ReadinessChip readiness={s.readiness} />
        </p>
        {s.reason ? (
          <p className="sign-reason">
            <span className="overline">Reason for signing off while not ready</span>
            {s.reason}
          </p>
        ) : null}
        <div className="sign-actions">
          <Button disabled title="Arrives with M8-07">
            Download PDF
          </Button>
          <Button disabled title="Arrives with M8-08">
            Copy share link
          </Button>
        </div>
      </div>
    )
  }

  const label = checking ? 'Checking…' : failed ? "Couldn't check" : `Sign off release ${release?.version ?? ''}`
  return (
    <div className="sign-box">
      <div className="sign-line" aria-hidden="true">
        <div>
          <span className="sign-name">&nbsp;</span>
          <span className="overline">Signed off by</span>
        </div>
        <div>
          <span className="sign-name">&nbsp;</span>
          <span className="overline">Date</span>
        </div>
      </div>
      <div className="sign-actions">
        {/* The only green control in the product. */}
        <Button variant="go" disabled={!release || checking || failed || !canSign} onClick={() => setOpen(true)}>
          {label}
        </Button>
        {!canSign ? <span className="faint small">Owners, admins and QA leads can sign off.</span> : null}
      </div>
      {release ? <SignOffDialog release={release} open={open} onOpenChange={setOpen} /> : null}
    </div>
  )
}

function SignOffDialog({ release, open, onOpenChange }: { release: ReleaseDetail; open: boolean; onOpenChange: (o: boolean) => void }) {
  const signOff = useSignOff(release.project_key, release.version)
  const [reason, setReason] = useState('')
  const ready = release.readiness === 'ready'

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!ready && !reason.trim()) return
    await signOff.mutateAsync(ready ? null : reason.trim())
    onOpenChange(false)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) signOff.reset()
        onOpenChange(o)
      }}
      title={ready ? `Sign off release ${release.version}` : `Release ${release.version} is not ready yet`}
      description={
        ready
          ? 'This freezes the report and records your name, the date and the readiness now.'
          : `${release.blockers.length} ${release.blockers.length === 1 ? 'blocker is' : 'blockers are'} still open. You can sign off anyway, with a written reason that stays on the record.`
      }
      width={560}
    >
      <form onSubmit={submit} className="dialog-form">
        {!ready ? (
          <>
            <ul className="dialog-blockers">
              {release.blockers.map((b) => (
                <li key={b.display_id}>
                  <Mark kind={BLOCKER[b.type].mark} size={14} />
                  <IdTag id={b.display_id} />
                  <span>{b.title}</span>
                </li>
              ))}
            </ul>
            <div className="field">
              <label className="field-label" htmlFor="signoff-reason">
                Reason for signing off anyway
              </label>
              <textarea
                id="signoff-reason"
                className="textarea"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="The client accepted the open risk on refunds in writing on 8 October."
                required
              />
            </div>
          </>
        ) : null}
        {signOff.isError ? <p className="field-error">Couldn't record the sign-off. Try again.</p> : null}
        <div className="dialog-actions">
          <DialogClose asChild>
            <Button variant="quiet">Cancel</Button>
          </DialogClose>
          <Button type="submit" variant="go" disabled={(!ready && !reason.trim()) || signOff.isPending}>
            {signOff.isPending ? 'Signing off…' : ready ? `Sign off release ${release.version}` : 'Sign off anyway'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
