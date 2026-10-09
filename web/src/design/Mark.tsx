// Status marks from the brand guide (section 06): 16 px grid, 1.7 px stroke, round ends.
// A mark never stands alone in the product; pair it with a word (see StatusChip).

export type MarkKind = 'pass' | 'fail' | 'hold' | 'open' | 'stale' | 'draft' | 'verified'

const STROKE = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.7,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const

export const MARK_COLOUR: Record<MarkKind, string> = {
  pass: 'var(--tick-deep)',
  fail: 'var(--stop)',
  hold: 'var(--hold-deep)',
  open: 'var(--graphite-deep)',
  stale: 'var(--graphite-deep)',
  draft: 'var(--pencil)',
  verified: 'var(--ink)',
}

type Props = {
  kind: MarkKind
  size?: number
  className?: string
  /** Use the status colour. Off when the parent sets the colour (chips). */
  coloured?: boolean
  /** Draw the tick in once (used when readiness turns Ready). */
  draw?: boolean
}

export function Mark({ kind, size = 16, className, coloured = true, draw = false }: Props) {
  return (
    <svg
      viewBox="0 0 16 16"
      width={Math.max(size, 12)}
      height={Math.max(size, 12)}
      aria-hidden="true"
      focusable="false"
      className={[draw ? 'mark-draw' : '', className ?? ''].join(' ').trim() || undefined}
      style={coloured ? { color: MARK_COLOUR[kind] } : undefined}
    >
      <g {...STROKE}>{paths(kind)}</g>
    </svg>
  )
}

function paths(kind: MarkKind) {
  switch (kind) {
    case 'pass':
      return <path pathLength={1} d="M3 8.7l3.2 3.3L13 3.6" />
    case 'fail':
      return <path d="M3.6 3.6l8.8 8.8M12.4 3.6l-8.8 8.8" />
    case 'hold':
      return <path d="M3 8h10" />
    case 'open':
      return <rect x="3" y="3" width="10" height="10" rx=".7" />
    case 'stale':
      return <rect x="3" y="3" width="10" height="10" rx=".7" strokeDasharray="2.2 1.9" />
    case 'draft':
      return <path d="M4 12.5L12 3.5" />
    case 'verified':
      return (
        <>
          <circle cx="8" cy="8" r="6.4" />
          <path pathLength={1} d="M5.2 8.4l2 2 3.7-4.3" style={{ stroke: 'var(--tick-mark, var(--tick))' }} />
        </>
      )
  }
}
