import { Link } from 'react-router'
import type { PlanCase } from '../../api/records'
import { IdTag } from '../../design/IdTag'
import { StatusChip } from '../../design/StatusChip'
import { SEVERITY_WORD as PRIORITY_WORD } from '../defects/DefectsList'

// One test case as it reads: steps, expected result and the requirements it covers. Shared by
// the plan page, the editor and the case page.
export function CaseView({ item, base, heading = true }: { item: PlanCase; base: string; heading?: boolean }) {
  return (
    <div className="case-view">
      {heading ? (
        <p className="case-view-head">
          <IdTag id={item.case} to={`${base}/cases/${item.number}`} />
          <span className="case-view-title">{item.title}</span>
          <span className="faint small">
            {PRIORITY_WORD[item.priority]} · r{item.revision}
          </span>
        </p>
      ) : null}
      {item.preconditions ? (
        <p className="muted">
          <span className="overline">Before you start</span> {item.preconditions}
        </p>
      ) : null}
      <ol className="case-steps">
        {item.steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
      <p className="case-expected">
        <span className="overline">Expected</span>
        {item.expected}
      </p>
      {item.requirements.length ? (
        <p className="case-reqs">
          <span className="overline">Covers</span>
          {item.requirements.map((r) => (
            <span key={r.display_id} className="case-req">
              <IdTag id={r.display_id} to={`${base}/requirements/${r.number}`} />
              <Link className="case-req-title" to={`${base}/requirements/${r.number}`}>
                {r.title}
              </Link>
              {r.stale ? <StatusChip status="stale" word="Requirement changed" /> : null}
            </span>
          ))}
        </p>
      ) : null}
    </div>
  )
}
