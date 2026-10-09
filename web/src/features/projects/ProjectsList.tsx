import { Link } from 'react-router'
import { useProjects } from '../../api/queries'
import { EmptyState, ErrorState, SkeletonRows } from '../../design/states'
import './projects.css'

export function ProjectsList() {
  const projects = useProjects()
  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Projects</h1>
          <p className="page-sub">Every product your team is testing, by its key.</p>
        </div>
      </header>
      {projects.isPending ? (
        <SkeletonRows rows={4} />
      ) : projects.isError ? (
        <ErrorState message="Couldn't load your projects." onRetry={() => projects.refetch()} />
      ) : !projects.data.length ? (
        <EmptyState title="No projects yet.">
          An owner or admin can create one in Settings. You will see the projects you are a member of here.
        </EmptyState>
      ) : (
        <ul className="ledger project-list">
          {projects.data.map((p) => (
            <li key={p.id} className="ledger-row">
              <span className="ledger-margin">
                <span className="project-key">{p.key}</span>
              </span>
              <Link to={`/${p.key.toLowerCase()}`} className="ledger-body project-link">
                <span className="project-name">{p.name}</span>
                {p.client_name ? <span className="faint">{p.client_name}</span> : null}
                <svg className="chev" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                  <path d="M6 3.5l4.5 4.5L6 12.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
