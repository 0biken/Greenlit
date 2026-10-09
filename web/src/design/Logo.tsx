import { LOGO_TICK, LOGO_VIEWBOX, LOGO_WORDMARK, TICK_ALONE, TICK_VIEWBOX } from './logoPaths'

// Drawn from the supplied logo files. On ink the tick lifts to a lighter green (guide 03).
export function Logo({ width = 104, reversed = false }: { width?: number; reversed?: boolean }) {
  return (
    <svg viewBox={LOGO_VIEWBOX} width={width} role="img" aria-label="Greenlit">
      <path fill={reversed ? 'var(--paper)' : 'var(--ink)'} d={LOGO_WORDMARK} />
      <path fill={reversed ? 'var(--tick-lift)' : 'var(--tick)'} d={LOGO_TICK} />
    </svg>
  )
}

export function TickIcon({ size = 18 }: { size?: number }) {
  return (
    <svg viewBox={TICK_VIEWBOX} width={size} aria-hidden="true">
      <path fill="var(--tick)" d={TICK_ALONE} />
    </svg>
  )
}
