import { Link } from 'react-router'
import { EmptyState } from '../design/states'

// Records you cannot see look exactly like records that do not exist (SEC: 404, never 403).
export function NotFound() {
  return (
    <EmptyState
      title="Nothing here."
      actions={
        <Link className="btn btn-secondary" to="/inbox">
          Go to Inbox
        </Link>
      }
    >
      The page doesn't exist, or it belongs to a project you aren't a member of.
    </EmptyState>
  )
}
