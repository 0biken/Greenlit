import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { useDefects } from '../../api/queries'
import { IdTag } from '../../design/IdTag'
import { Mark } from '../../design/Mark'
import { EmptyState, ErrorState, SkeletonRows } from '../../design/states'
import { STATUS, StatusChip } from '../../design/StatusChip'
import { ProjectNav } from '../projects/ProjectNav'
import './defects.css'

// Defect list (M5-09): open work first, each row with its mark, ID, label, severity and age.

const STATES = [
  { id: '', label: 'All' },
  { id: 'retest_failed', label: 'Retest failed' },
  { id: 'needs_retest', label: 'Needs retest' },
  { id: 'open', label: 'Open' },
  { id: 'verified', label: 'Verified' },
  { id: 'decided', label: "Won't fix or deferred" },
]

export const SEVERITY_WORD = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low' } as const

export function DefectsList() {
  const { projectKey = '' } = useParams()
  const key = projectKey.toUpperCase()
  const [params, setParams] = useSearchParams()
  const state = params.get('state') ?? ''
  const [search, setSearch] = useState(params.get('q') ?? '')
  const q = params.get('q') ?? ''
  const defects = useDefects(key, { state, q })
  const base = `/${projectKey.toLowerCase()}/bugs`

  function setFilter(next: Record<string, string>) {
    const merged = { state, q, ...next }
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
          <h1 className="page-title">Defects</h1>
        </div>
        <Link className="btn btn-primary" to={`${base}/new`}>
          File a defect
        </Link>
      </header>
      <ProjectNav projectKey={projectKey} />

      <div className="list-tools">
        <div className="chip-filters" role="group" aria-label="Filter by state">
          {STATES.map((s) => (
            <button
              key={s.id}
              type="button"
              className="filter"
              aria-current={state === s.id ? 'true' : undefined}
              onClick={() => setFilter({ state: s.id })}
            >
              {s.label}
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
          <label className="sr-only" htmlFor="defect-search">
            Search defects by title or number
          </label>
          <input
            id="defect-search"
            className="input search-input"
            type="search"
            placeholder="Title or BUG number"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              if (!e.target.value) setFilter({ q: '' })
            }}
          />
        </form>
      </div>

      {defects.isPending ? (
        <SkeletonRows rows={6} />
      ) : defects.isError && !defects.data ? (
        <ErrorState message="Couldn't load the defects." onRetry={() => defects.refetch()} />
      ) : !defects.data.length ? (
        state || q ? (
          <EmptyState title="No defects match these filters." />
        ) : (
          <EmptyState
            title="No defects on this project."
            actions={
              <Link className="btn btn-secondary" to={`${base}/new`}>
                File a defect
              </Link>
            }
          />
        )
      ) : (
        <ul className="ledger defect-list">
          {defects.data.map((d) => (
            <li key={d.id} className="ledger-row">
              <span className="ledger-margin">
                <span>{d.age_days === 0 ? 'new' : `${d.age_days}d`}</span>
                <Mark kind={STATUS[d.chip].mark} />
              </span>
              <Link to={`${base}/${d.display_id.split('-')[1]}`} className="ledger-body defect-row">
                <span className="defect-main">
                  <IdTag id={d.display_id} />
                  <span className="defect-title">{d.title}</span>
                </span>
                <span className="defect-meta">
                  <span>{SEVERITY_WORD[d.severity]}</span>
                  {d.owner_name ? <span>{d.owner_name}</span> : <span>No owner</span>}
                  {d.release ? <span className="mono">{d.release}</span> : null}
                </span>
                <span className="defect-status">
                  <StatusChip status={d.chip} word={d.shown_as} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
