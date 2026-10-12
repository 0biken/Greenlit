import type { Readiness } from '../../api/records'
import { Mark } from '../../design/Mark'

// Readiness is Ready or Not ready yet (vocabulary, guide 11). Ready is one of the few green
// things in the product; "Checking…" and "Couldn't check" are states of the check itself.
export function ReadinessChip({ readiness, draw = false }: { readiness: Readiness | 'checking' | 'unknown'; draw?: boolean }) {
  if (readiness === 'checking') {
    return (
      <span className="chip chip-open" role="status">
        <Mark kind="open" size={13} coloured={false} /> Checking…
      </span>
    )
  }
  if (readiness === 'unknown') {
    return (
      <span className="chip chip-hold" role="img" aria-label="Readiness: couldn't check">
        <Mark kind="hold" size={13} coloured={false} /> Couldn't check
      </span>
    )
  }
  const ready = readiness === 'ready'
  return (
    <span className={`chip ${ready ? 'chip-pass' : 'chip-hold'}`} role="img" aria-label={`Readiness: ${ready ? 'Ready' : 'Not ready yet'}`}>
      <Mark kind={ready ? 'pass' : 'hold'} size={13} coloured={false} draw={ready && draw} />
      <span aria-hidden="true">{ready ? 'Ready' : 'Not ready yet'}</span>
    </span>
  )
}
