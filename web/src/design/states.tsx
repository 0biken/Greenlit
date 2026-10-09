import type { ReactNode } from 'react'
import { Button } from './Button'

// Empty, loading and error states (UX "Empty, loading and error states").
// An empty screen always says what to do next.

export function EmptyState({ title, children, actions }: { title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="state state-empty">
      <p className="state-title">{title}</p>
      {children ? <div className="state-body">{children}</div> : null}
      {actions ? <div className="state-actions">{actions}</div> : null}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <p className="state-title">{message}</p>
      {onRetry ? (
        <div className="state-actions">
          <Button onClick={onRetry}>Retry</Button>
        </div>
      ) : null}
    </div>
  )
}

/** Skeleton rows shaped like the real ledger rows they stand in for. */
export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="skeleton-rows" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div className="ledger-row skeleton-row" key={i}>
          <span className="ledger-margin">
            <span className="skel skel-mark" />
          </span>
          <span className="ledger-body">
            <span className="skel skel-id" />
            <span className="skel" style={{ width: `${40 + ((i * 17) % 35)}%` }} />
          </span>
        </div>
      ))}
    </div>
  )
}
