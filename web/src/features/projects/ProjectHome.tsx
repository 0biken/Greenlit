import { Link, useParams } from 'react-router'
import type { Coverage, OpenWorkRow, ProjectSummary } from '../../api/planned'
import { useProjects, useProjectSummary } from '../../api/queries'
import { Button } from '../../design/Button'
import { IdTag } from '../../design/IdTag'
import { Mark, type MarkKind } from '../../design/Mark'
import { EmptyState, ErrorState, SkeletonRows } from '../../design/states'
import { NotFound } from '../NotFound'
import { ReadinessChip } from '../releases/ReadinessChip'
import './projects.css'

// Project home: the dashboard (UX screen 4). A ledger, not a wall of charts: the release,
// how much is verified with evidence, and the open work, each linking to the records.

const OPEN_WORK: Record<OpenWorkRow['kind'], { label: string; mark: MarkKind }> = {
  retest_failed: { label: 'Retest failed', mark: 'fail' },
  needs_retest: { label: 'Fixed but not retested', mark: 'hold' },
  unfiled_failures: { label: 'Failures without a defect', mark: 'fail' },
  missing_evidence: { label: 'Results missing evidence', mark: 'hold' },
  stale: { label: 'Stale tests', mark: 'stale' },
  uncovered: { label: 'Requirements without tests', mark: 'open' },
}
const OPEN_ORDER: OpenWorkRow['kind'][] = ['retest_failed', 'needs_retest', 'unfiled_failures', 'missing_evidence', 'stale', 'uncovered']

export function ProjectHome() {
  const { projectKey = '' } = useParams()
  const key = projectKey.toUpperCase()
  const projects = useProjects()
  const summary = useProjectSummary(key)
  const project = projects.data?.find((p) => p.key.toUpperCase() === key)

  // Projects the member cannot see are "not found", exactly like the API's 404.
  if (projects.isSuccess && !project) return <NotFound />
  if (summary.isPending || projects.isPending) {
    return (
      <div>
        <header className="page-head">
          <div>
            <p className="crumbs">
              <Link to="/projects">Projects</Link>
            </p>
            <h1 className="page-title">{key}</h1>
          </div>
        </header>
        <SkeletonRows rows={6} />
      </div>
    )
  }
  if (summary.isError) return <ErrorState message="Couldn't load this project." onRetry={() => summary.refetch()} />

  const s: ProjectSummary = { ...summary.data, name: project?.name ?? summary.data.name, client_name: project?.client_name ?? summary.data.client_name }
  return (
    <div className="project">
      <header className="page-head">
        <div>
          <p className="crumbs">
            <Link to="/projects">Projects</Link>
            <span aria-hidden="true">/</span>
            <span className="mono">{s.key}</span>
          </p>
          <h1 className="page-title">{s.name}</h1>
          {s.client_name ? <p className="page-sub">For {s.client_name}</p> : null}
          <Link className="btn btn-secondary btn-sm project-requirements-link" to={`/${s.key.toLowerCase()}/requirements`}>Requirements</Link>
        </div>
      </header>

      {s.is_new ? (
        <FirstVisit />
      ) : (
        <>
          {s.release ? <ReleaseStrip projectKey={s.key} release={s.release} /> : null}
          <div className="dash-grid">
            <section className="dash-section" aria-labelledby="coverage-h">
              <h2 id="coverage-h" className="overline dash-h">
                Verified coverage
              </h2>
              {s.coverage ? <CoverageBlock coverage={s.coverage} /> : <p className="faint">No release yet.</p>}
              <dl className="counts">
                <Count label="Requirements" value={s.counts.requirements} />
                <Count label="Test cases" value={s.counts.cases} />
                <Count label="Runs" value={s.counts.runs} />
                <Count label="Open defects" value={s.counts.open_defects} />
              </dl>
            </section>

            <section className="dash-section" aria-labelledby="open-h">
              <h2 id="open-h" className="overline dash-h">
                Open work
              </h2>
              <ul className="ledger open-work">
                {OPEN_ORDER.map((kind) => {
                  const row = s.open_work.find((w) => w.kind === kind) ?? { kind, count: 0, oldest_days: null }
                  const def = OPEN_WORK[kind]
                  const clear = row.count === 0
                  return (
                    <li key={kind} className="ledger-row" data-clear={clear || undefined}>
                      <span className="ledger-margin">
                        <span className="open-count">{row.count}</span>
                        {clear ? <span className="mark-gap" /> : <Mark kind={def.mark} />}
                      </span>
                      <span className="ledger-body">
                        <span className="open-label">{def.label}</span>
                        <span className="faint open-age">
                          {clear ? 'None' : row.oldest_days !== null ? `oldest ${row.oldest_days}d` : ''}
                        </span>
                      </span>
                    </li>
                  )
                })}
              </ul>
            </section>
          </div>

          <section className="dash-section activity" aria-labelledby="activity-h">
            <h2 id="activity-h" className="overline dash-h">
              Recent activity
            </h2>
            {s.activity.length ? (
              <ol className="activity-list">
                {s.activity.map((a, i) => (
                  <li key={i}>
                    <time className="mono faint" dateTime={a.at}>
                      {formatWhen(a.at)}
                    </time>
                    <span>
                      <strong>{a.actor}</strong> <Linkified text={a.text} refs={a.refs} projectKey={s.key} />
                    </span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="faint">Nothing recorded yet.</p>
            )}
          </section>
        </>
      )}
    </div>
  )
}

function ReleaseStrip({ projectKey, release }: { projectKey: string; release: NonNullable<ProjectSummary['release']> }) {
  const to = `/${projectKey.toLowerCase()}/releases/${release.version}`
  return (
    <section className="release-strip" aria-label={`Release ${release.version}`}>
      <div className="release-strip-main">
        <span className="overline">Next release</span>
        <span className="release-strip-version">{release.version}</span>
        {release.due ? (
          <span className="faint">due {new Date(release.due).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })}</span>
        ) : null}
      </div>
      <div className="release-strip-state">
        <ReadinessChip readiness={release.readiness} />
        {release.blockers ? (
          <span className="muted">
            {release.blockers} {release.blockers === 1 ? 'blocker' : 'blockers'}
          </span>
        ) : null}
        <Link className="btn btn-secondary btn-sm" to={to}>
          Open release
        </Link>
      </div>
    </section>
  )
}

export function CoverageBlock({ coverage }: { coverage: Coverage }) {
  return (
    <div className="coverage">
      <p className="coverage-figure">
        <span className="coverage-pct">{coverage.verified_pct}%</span>
        <span className="muted">of requirements verified with evidence</span>
      </p>
      <div
        className="prog"
        role="meter"
        aria-label="Verified coverage"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={coverage.verified_pct}
      >
        <i style={{ transform: `scaleX(${coverage.verified_pct / 100})` }} />
      </div>
      <p className="coverage-breakdown">
        <span>
          <Mark kind="verified" size={14} /> Verified {coverage.verified}
        </span>
        <span>
          <Mark kind="hold" size={14} /> On hold {coverage.on_hold}
        </span>
        <span>
          <Mark kind="fail" size={14} /> Failed {coverage.failed}
        </span>
        <span>
          <Mark kind="open" size={14} /> Not run {coverage.not_run}
        </span>
      </p>
    </div>
  )
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt className="faint">{label}</dt>
      <dd className="mono">{value}</dd>
    </div>
  )
}

function FirstVisit() {
  return (
    <EmptyState
      title="Start with a PRD, screenshots, or an old QA report."
      actions={
        <>
          <Button variant="primary" disabled title="Arrives with Sources (M2)">
            Upload a PRD
          </Button>
          <Button disabled title="Arrives with Sources (M7)">
            Add screenshots
          </Button>
          <Button disabled title="Arrives with Sources (M7)">
            Import a QA report
          </Button>
        </>
      }
    >
      Greenlit drafts requirements and test cases from them. You review every draft before it counts.
    </EmptyState>
  )
}

const ROUTE_FOR: Record<string, string> = { BUG: 'bugs', TC: 'cases', REQ: 'requirements', RUN: 'runs', TP: 'plans', EV: 'evidence', RPT: 'reports' }

/** Turn the record IDs inside a sentence into clickable ID tags. */
export function Linkified({ text, refs, projectKey }: { text: string; refs: string[]; projectKey: string }) {
  if (!refs.length) return <>{text}</>
  const pattern = new RegExp(`(${refs.map((r) => r.replace(/[-]/g, '\\-')).join('|')})`, 'g')
  return (
    <>
      {text.split(pattern).map((part, i) => {
        if (!refs.includes(part)) return <span key={i}>{part}</span>
        const [prefix, no] = part.split('-')
        return <IdTag key={i} id={part} to={`/${projectKey.toLowerCase()}/${ROUTE_FOR[prefix] ?? 'records'}/${no}`} />
      })}
    </>
  )
}

function formatWhen(iso: string) {
  const d = new Date(iso)
  const today = new Date()
  const yesterday = new Date(Date.now() - 86_400_000)
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  if (d.toDateString() === today.toDateString()) return `Today ${time}`
  if (d.toDateString() === yesterday.toDateString()) return `Yesterday ${time}`
  return `${d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })} ${time}`
}
