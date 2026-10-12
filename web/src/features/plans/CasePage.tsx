import { Link, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { useCase } from '../../api/queries'
import type { Outcome } from '../../api/records'
import { IdTag } from '../../design/IdTag'
import { ErrorState, SkeletonRows } from '../../design/states'
import { StatusChip, type Status } from '../../design/StatusChip'
import { SEVERITY_WORD as PRIORITY_WORD } from '../defects/DefectsList'
import { NotFound } from '../NotFound'
import { ProjectNav } from '../projects/ProjectNav'
import { CaseView } from './CaseView'
import '../defects/defects.css'
import './plans.css'

// One test case: what it says now, the plans it is in, how it last went, and its revisions.
// Cases are edited inside a plan's draft, so this page links there instead of editing here.

const when = (iso: string) =>
  new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

export function CasePage() {
  const { projectKey = '', no = '' } = useParams()
  const key = projectKey.toUpperCase()
  const base = `/${projectKey.toLowerCase()}`
  const item = useCase(key, no)

  if (item.error instanceof ApiError && item.error.isNotFound) return <NotFound />
  if (item.isPending) return <SkeletonRows rows={6} />
  if (item.isError) return <ErrorState message="Couldn't load this test case." onRetry={() => item.refetch()} />
  const c = item.data

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
            <IdTag id={c.case} /> {c.title}
          </h1>
          <p className="page-sub defect-facts">
            <span>{PRIORITY_WORD[c.priority]} priority</span>
            <span>Revision {c.revision}</span>
            {c.retired ? <span>Retired</span> : null}
          </p>
        </div>
      </header>
      <ProjectNav projectKey={projectKey} />

      <div className="defect-layout">
        <div className="defect-record">
          <CaseView item={c} base={base} heading={false} />
        </div>
        <aside className="defect-side">
          <h2 className="dash-h">In these plans</h2>
          {c.plans.length ? (
            <ul className="plain-list">
              {c.plans.map((p) => (
                <li key={`${p.display_id}-${p.version ?? 'draft'}`} className="link-row">
                  <IdTag id={p.display_id} to={`${base}/plans/${p.number}${p.version ? '' : '?v=draft'}`} />
                  <span className="link-row-title">{p.title}</span>
                  <span className="faint small">
                    {p.version ? `v${p.version}` : 'Draft'} · r{p.revision}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="faint">Not in any current plan.</p>
          )}

          <h2 className="dash-h">Recent results</h2>
          {c.results.length ? (
            <ul className="plain-list">
              {c.results.map((r, i) => (
                <li key={i} className="link-row">
                  <IdTag id={r.run} to={`${base}/runs/${r.run_no}`} />
                  <StatusChip status={r.outcome as Outcome as Status} />
                  <span className="faint small">
                    {when(r.at)} · r{r.revision}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="faint">Not run yet.</p>
          )}

          <h2 className="dash-h">Revisions</h2>
          <ul className="history-list">
            {c.revisions.map((r) => (
              <li key={r.revision}>
                <span className="mono">r{r.revision}</span> {r.title}{' '}
                <span className="faint small">
                  {r.by ? `${r.by}, ` : ''}
                  {when(r.at)}
                </span>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  )
}
