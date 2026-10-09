import { Link } from 'react-router'

// Display IDs (REQ-102, BUG-1042, v1.4) in mono. Clickable wherever they appear (UX rule 2).
export function IdTag({ id, to }: { id: string; to?: string }) {
  if (!to) return <span className="id">{id}</span>
  return (
    <Link className="id id-link" to={to}>
      {id}
    </Link>
  )
}
