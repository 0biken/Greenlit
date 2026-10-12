import { useState } from 'react'
import { useParams } from 'react-router'
import { downloadSharedPdf, useSharedReport } from '../../api/queries'
import { Button } from '../../design/Button'
import { IdTag } from '../../design/IdTag'
import { Logo } from '../../design/Logo'
import { Mark, type MarkKind } from '../../design/Mark'
import '../releases/release.css'
import './shared.css'

// What a share link opens (FR-RPT-04): the signed report and its sign-off, as they were
// signed. No sign-in. Record IDs are shown but not linked: the reader has no account.

const BLOCKER: Record<string, { label: string; mark: MarkKind }> = {
  closed_failed_retest: { label: 'Closed with a failed retest', mark: 'fail' },
  open_critical: { label: 'Open critical defect', mark: 'fail' },
  needs_retest: { label: 'Fixed but not retested', mark: 'hold' },
  unfiled_failure: { label: 'Failure without a defect', mark: 'fail' },
  uncovered_critical: { label: 'Critical requirement without tests', mark: 'open' },
}

export function SharedReportPage() {
  const { token = '' } = useParams()
  const shared = useSharedReport(token)
  const [downloading, setDownloading] = useState(false)
  const [problem, setProblem] = useState(false)

  if (shared.isPending) return <div className="shared-page" aria-busy="true" />
  if (shared.isError) {
    return (
      <div className="shared-page">
        <main className="shared-sheet">
          <Logo width={110} />
          <h1 className="shared-title">This link doesn't open a report.</h1>
          <p className="muted">
            It may have expired or been withdrawn. Ask whoever sent it to you for a new one.
          </p>
        </main>
      </div>
    )
  }

  const r = shared.data
  const ready = r.sign_off.readiness === 'ready'

  async function pdf() {
    setProblem(false)
    setDownloading(true)
    try {
      await downloadSharedPdf(token)
    } catch {
      setProblem(true)
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="shared-page">
      <main className="shared-sheet">
        <header className="shared-head">
          <Logo width={96} />
          <span className="overline">
            Release report <span className="mono">{r.report.display_id}</span>
          </span>
        </header>

        <p className="faint">
          {r.organisation} · {r.project}
        </p>
        <h1 className="shared-title">
          Release <span className="mono-title">{r.version}</span>
        </h1>
        <p className="shared-readiness">
          <Mark kind={ready ? 'pass' : 'hold'} size={18} /> {ready ? 'Ready' : 'Not ready yet'}{' '}
          <span className="faint">at sign-off</span>
        </p>
        <p className="report-summary">{r.report.summary}</p>

        {r.blockers.length ? (
          <section>
            <h2 className="overline shared-h">Blockers at sign-off · {r.blockers.length}</h2>
            <ul className="shared-rows">
              {r.blockers.map((b) => (
                <li key={b.display_id} className="ledger-row">
                  <span className="ledger-margin">
                    <Mark kind={BLOCKER[b.type]?.mark ?? 'open'} />
                  </span>
                  <span className="ledger-body">
                    <IdTag id={b.display_id} />
                    <span>{b.title}</span>
                    <span className="faint small shared-kind">{BLOCKER[b.type]?.label}</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {r.report.sections.map((section) => (
          <section key={section.heading} className="report-section">
            <h2 className="overline shared-h">{section.heading}</h2>
            <ul>
              {section.lines.map((line, i) => (
                <li key={i}>
                  {line.text}
                  <span className="report-refs">
                    {line.refs.map((ref) => (
                      <IdTag key={ref} id={ref} />
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}

        <div className="sign-box signed">
          <div className="sign-line">
            <div>
              <span className="sign-name">{r.sign_off.by}</span>
              <span className="overline">Signed off by</span>
            </div>
            <div>
              <span className="sign-name mono">
                {new Date(r.sign_off.at).toLocaleString('en-GB', {
                  day: 'numeric',
                  month: 'short',
                  year: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </span>
              <span className="overline">Date</span>
            </div>
          </div>
          {r.sign_off.reason ? (
            <p className="sign-reason">
              <span className="overline">Reason for signing off while not ready</span>
              {r.sign_off.reason}
            </p>
          ) : null}
          <div className="sign-actions">
            <Button onClick={pdf} disabled={downloading}>
              {downloading ? 'Preparing…' : 'Download PDF'}
            </Button>
            {problem ? <span className="field-error">Couldn't download the PDF. Try again.</span> : null}
          </div>
        </div>

        <footer className="shared-foot faint small">
          This is the signed copy. It does not change after sign-off. The link works until{' '}
          {new Date(r.expires_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}.
        </footer>
      </main>
    </div>
  )
}
