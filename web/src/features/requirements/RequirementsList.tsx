import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { useRequirements } from '../../api/queries'
import { useOrg } from '../../app/Gate'
import { IdTag } from '../../design/IdTag'
import { Mark } from '../../design/Mark'
import { EmptyState, ErrorState, SkeletonRows } from '../../design/states'
import { StatusChip } from '../../design/StatusChip'
import { SEVERITY_WORD as PRIORITY_WORD } from '../defects/DefectsList'
import { ProjectNav } from '../projects/ProjectNav'
import '../defects/defects.css'
import '../plans/plans.css'

// Requirements (M2-08): what must be true, and whether a test case covers each one.

const COVERAGE = [
  { id: '', label: 'All' },
  { id: 'uncovered', label: 'No test cases' },
  { id: 'covered', label: 'Covered' },
]
export const CAN_WRITE = ['owner', 'admin', 'qa_lead', 'qa_engineer']

export function RequirementsList() {
  const { projectKey = '' } = useParams()
  const key = projectKey.toUpperCase()
  const { membership } = useOrg()
  const [params, setParams] = useSearchParams()
  const coverage = params.get('coverage') ?? ''
  const q = params.get('q') ?? ''
  const [search, setSearch] = useState(q)
  const requirements = useRequirements(key, { coverage, q })
  const base = `/${projectKey.toLowerCase()}/requirements`
  const canWrite = CAN_WRITE.includes(membership.role)

  function setFilter(next: Record<string, string>) {
    const merged = { coverage, q, ...next }
    setParams(Object.fromEntries(Object.entries(merged).filter(([, v]) => v)), { replace: true })
  }

  return (
    <div>
      <header className="page-head">
        <div>
          <p className="crumbs">
            <Link to="/projects">Projects</Link>
            <span aria-hidden="true">/</span>
            <span className="mono">{key}</span>
          </p>
          <h1 className="page-title">Requirements</h1>
        </div>
        {canWrite ? (
          <Link className="btn btn-primary" to={`${base}/new`}>
            Add a requirement
          </Link>
        ) : null}
      </header>
      <ProjectNav projectKey={projectKey} />

      <div className="list-tools">
        <div className="chip-filters" role="group" aria-label="Filter by coverage">
          {COVERAGE.map((c) => (
            <button
              key={c.id}
              type="button"
              className="filter"
              aria-current={coverage === c.id ? 'true' : undefined}
              onClick={() => setFilter({ coverage: c.id })}
            >
              {c.label}
            </button>
          ))}
        </div>
        <form
          role="search"
          onSubmit={(e) => {
            e.preventDefault()
            setFilter({ q: search.trim() })
          }}
        >
          <label className="sr-only" htmlFor="requirement-search">
            Search requirements by words or number
          </label>
          <input
            id="requirement-search"
            className="input search-input"
            type="search"
            placeholder="Words or REQ number"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              if (!e.target.value) setFilter({ q: '' })
            }}
          />
        </form>
      </div>

      {requirements.isPending ? (
        <SkeletonRows rows={6} />
      ) : requirements.isError && !requirements.data ? (
        <ErrorState message="Couldn't load the requirements." onRetry={() => requirements.refetch()} />
      ) : !requirements.data.length ? (
        coverage || q ? (
          <EmptyState title="No requirements match these filters." />
        ) : (
          <EmptyState
            title="No requirements on this project yet."
            actions={
              canWrite ? (
                <Link className="btn btn-secondary" to={`${base}/new`}>
                  Add a requirement
                </Link>
              ) : undefined
            }
          >
            A requirement is one thing that must be true. Test cases are written against them.
          </EmptyState>
        )
      ) : (
        <ul className="ledger defect-list">
          {requirements.data.map((r) => (
            <li key={r.id} className="ledger-row">
              <span className="ledger-margin">
                <span>r{r.revision}</span>
                <Mark kind={r.covered ? (r.stale_cases ? 'stale' : 'pass') : 'open'} />
              </span>
              <Link to={`${base}/${r.number}`} className="ledger-body defect-row">
                <span className="defect-main">
                  <IdTag id={r.display_id} />
                  <span className="defect-title">{r.title}</span>
                </span>
                <span className="defect-meta">
                  <span>{PRIORITY_WORD[r.priority]}</span>
                  <span>
                    {r.cases} {r.cases === 1 ? 'case' : 'cases'}
                  </span>
                  {r.review_state === 'draft' ? <span>Draft</span> : null}
                </span>
                <span className="defect-status">
                  {!r.covered ? (
                    <StatusChip status="uncovered" />
                  ) : r.stale_cases ? (
                    <StatusChip status="stale" word={r.stale_cases === 1 ? '1 stale case' : `${r.stale_cases} stale cases`} />
                  ) : (
                    <span className="faint small">Covered</span>
                  )}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
