import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { Logo } from '../../design/Logo'
import './auth.css'

// Paper page, one narrow column, the margin rule from the ledger layout on wide screens.
export function AuthLayout({ title, lead, children, footer }: { title: string; lead?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="auth">
      <aside className="auth-side" aria-hidden="true">
        <p className="auth-motto">
          Ship with <em>proof.</em>
        </p>
        <p className="auth-promise">
          If it was found, it is filed. If it was fixed, it was retested. If it shipped, there is proof.
        </p>
      </aside>
      <main className="auth-main">
        <Link to="/sign-in" className="auth-logo" aria-label="Greenlit">
          <Logo width={132} />
        </Link>
        <h1 className="auth-title">{title}</h1>
        {lead ? <p className="auth-lead">{lead}</p> : null}
        {children}
        {footer ? <div className="auth-footer">{footer}</div> : null}
      </main>
    </div>
  )
}

export function FormError({ message }: { message?: string }) {
  if (!message) return null
  return (
    <p className="form-error" role="alert">
      {message}
    </p>
  )
}

export function Field({
  label,
  error,
  hint,
  ...input
}: React.InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string; hint?: string }) {
  const id = input.id ?? input.name
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      <input className="input" id={id} aria-invalid={error ? true : undefined} aria-describedby={describedBy} {...input} />
      {error ? (
        <span className="field-error" id={`${id}-error`}>
          {error}
        </span>
      ) : hint ? (
        <span className="field-hint" id={`${id}-hint`}>
          {hint}
        </span>
      ) : null}
    </div>
  )
}
