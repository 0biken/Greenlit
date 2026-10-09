import { useMembers } from '../../api/queries'
import { useOrg } from '../../app/Gate'
import { ErrorState, SkeletonRows } from '../../design/states'
import '../projects/projects.css'

const ROLE_WORD: Record<string, string> = {
  owner: 'Owner',
  admin: 'Admin',
  qa_lead: 'QA lead',
  qa_engineer: 'QA engineer',
  developer: 'Developer',
  viewer: 'Viewer',
}

// First cut of Settings: the organisation and its members (read-only). Inviting, changing
// roles and project settings come with the rest of M1-19's screens.
export function SettingsPage() {
  const { membership } = useOrg()
  const members = useMembers()
  return (
    <div>
      <header className="page-head">
        <div>
          <h1 className="page-title">Settings</h1>
          <p className="page-sub">
            {membership.organisation.name} <span className="mono faint">/{membership.organisation.slug}</span>
          </p>
        </div>
      </header>
      <section aria-labelledby="members-h">
        <h2 id="members-h" className="overline dash-h">
          Members
        </h2>
        {members.isPending ? (
          <SkeletonRows rows={4} />
        ) : members.isError ? (
          <ErrorState message="Couldn't load the members." onRetry={() => members.refetch()} />
        ) : (
          <ul className="ledger project-list" style={{ borderTop: 0, marginTop: -20 }}>
            {members.data.map((m) => (
              <li key={m.user_id} className="ledger-row">
                <span className="ledger-margin">{ROLE_WORD[m.role] ?? m.role}</span>
                <span className="ledger-body">
                  <span className="project-name">{m.name || m.email}</span>
                  <span className="faint">{m.email}</span>
                  {m.status !== 'active' ? <span className="faint small">{m.status}</span> : null}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
