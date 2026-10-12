import { NavLink } from 'react-router'
import './projects.css'

// Inside a project, in the order work usually happens (UX navigation map). Screens that are
// not built yet (sources) join this row as they arrive.
export function ProjectNav({ projectKey }: { projectKey: string }) {
  const base = `/${projectKey.toLowerCase()}`
  return (
    <nav className="project-nav" aria-label={`${projectKey.toUpperCase()} sections`}>
      <NavLink to={base} end>
        Home
      </NavLink>
      <NavLink to={`${base}/requirements`}>Requirements</NavLink>
      <NavLink to={`${base}/plans`}>Plans</NavLink>
      <NavLink to={`${base}/runs`}>Runs</NavLink>
      <NavLink to={`${base}/bugs`}>Defects</NavLink>
      <NavLink to={`${base}/releases`}>Releases</NavLink>
    </nav>
  )
}
