import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { renderSVG } from 'uqr'
import { auth, authError, type AuthResult } from '../../api/client'
import { keys } from '../../api/queries'
import { Button } from '../../design/Button'
import { AuthLayout, Field, FormError } from './AuthLayout'
import { safeNext, sessionKey, useSession } from './session'

// Sign-in screens over allauth's headless API (docs/sign-in.md). allauth answers 401 for a
// step that is still pending (verify email, second step); those move the person on, not back.

function useAuthForm() {
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<AuthResult | null>(null)
  const [failed, setFailed] = useState(false)
  async function run(path: string, body: unknown) {
    setBusy(true)
    setFailed(false)
    try {
      const r = await auth(path, { method: 'POST', body })
      setResult(r)
      return r
    } catch {
      setFailed(true)
      return null
    } finally {
      setBusy(false)
    }
  }
  const formError = failed ? "Couldn't reach Greenlit. Check your connection and try again." : authError(result)
  return { busy, result, run, formError }
}

export function SignIn() {
  const navigate = useNavigate()
  const client = useQueryClient()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const { busy, result, run, formError } = useAuthForm()
  const session = useSession()

  // Already signed in (a bookmark, or the back button): go straight on.
  useEffect(() => {
    if (session.data?.authenticated) navigate(next, { replace: true })
  }, [session.data?.authenticated, navigate, next])

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    const r = await run('/auth/login', { email: form.get('email'), password: form.get('password') })
    if (!r) return
    if (r.authenticated) {
      await client.invalidateQueries({ queryKey: sessionKey })
      navigate(next, { replace: true })
    } else if (r.pending === 'mfa_authenticate') {
      navigate(`/two-step?next=${encodeURIComponent(next)}`)
    }
  }

  const unverified = result?.pending === 'verify_email'
  return (
    <AuthLayout
      title="Sign in"
      lead="Pick up where the release left off."
      footer={
        <>
          New to Greenlit? <Link to="/sign-up">Create an account</Link>
        </>
      }
    >
      <form className="auth-form" onSubmit={submit} noValidate>
        {params.get('error') === 'social' ? <FormError message="Google sign-in didn't finish. Try again, or use your email." /> : null}
        {unverified ? (
          <p className="notice" role="status">
            Confirm your email address first. We sent a link when you signed up.
          </p>
        ) : (
          <FormError message={formError} />
        )}
        <Field label="Email" name="email" type="email" autoComplete="email" required error={authError(result, 'email')} />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          error={authError(result, 'password')}
        />
        <div className="auth-row">
          <span />
          <Link to="/reset-password">Forgotten your password?</Link>
        </div>
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
    </AuthLayout>
  )
}

export function TwoStep() {
  const navigate = useNavigate()
  const client = useQueryClient()
  const [params] = useSearchParams()
  const { busy, result, run, formError } = useAuthForm()

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const code = String(new FormData(e.currentTarget).get('code') ?? '').replace(/\s/g, '')
    const r = await run('/auth/2fa/authenticate', { code })
    if (r?.authenticated) {
      await client.invalidateQueries({ queryKey: sessionKey })
      navigate(safeNext(params.get('next')), { replace: true })
    }
  }

  return (
    <AuthLayout
      title="Two-step verification"
      lead="Enter the 6-digit code from your authenticator app, or one of your recovery codes."
      footer={<Link to="/sign-in">Use a different account</Link>}
    >
      <form className="auth-form" onSubmit={submit} noValidate>
        <FormError message={formError} />
        <Field
          label="Code"
          name="code"
          inputMode="numeric"
          autoComplete="one-time-code"
          autoFocus
          required
          className="input input-code"
          error={authError(result, 'code')}
        />
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? 'Checking…' : 'Verify'}
        </Button>
      </form>
    </AuthLayout>
  )
}

export function SignUp() {
  const { busy, result, run, formError } = useAuthForm()
  const [sentTo, setSentTo] = useState<string | null>(null)

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    const email = String(form.get('email'))
    const r = await run('/auth/signup', { name: form.get('name'), email, password: form.get('password') })
    if (r?.pending === 'verify_email') setSentTo(email)
  }

  if (sentTo) {
    return (
      <AuthLayout
        title="Check your email"
        lead={
          <>
            We sent a link to <strong>{sentTo}</strong>. Open it to confirm your address, then sign in.
          </>
        }
        footer={<Link to="/sign-in">Back to sign in</Link>}
      >
        {null}
      </AuthLayout>
    )
  }

  return (
    <AuthLayout
      title="Create your account"
      lead="One record of what was tested, found and fixed."
      footer={
        <>
          Already have an account? <Link to="/sign-in">Sign in</Link>
        </>
      }
    >
      <form className="auth-form" onSubmit={submit} noValidate>
        <FormError message={formError} />
        <Field label="Your name" name="name" autoComplete="name" required error={authError(result, 'name')} />
        <Field label="Work email" name="email" type="email" autoComplete="email" required error={authError(result, 'email')} />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="new-password"
          required
          hint="At least 12 characters."
          error={authError(result, 'password')}
        />
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? 'Creating account…' : 'Create account'}
        </Button>
      </form>
    </AuthLayout>
  )
}

export function VerifyEmail() {
  const { key = '' } = useParams()
  const client = useQueryClient()
  const navigate = useNavigate()
  const [state, setState] = useState<'checking' | 'verified' | 'invalid' | 'offline'>('checking')
  const sent = useRef(false)

  useEffect(() => {
    if (sent.current) return // the key is single use; StrictMode would send it twice
    sent.current = true
    auth('/auth/email/verify', { method: 'POST', body: { key } })
      .then(async (r) => {
        if (r.authenticated) {
          await client.invalidateQueries({ queryKey: sessionKey })
          navigate('/inbox', { replace: true })
        } else setState(r.status === 401 ? 'verified' : 'invalid')
      })
      .catch(() => setState('offline'))
  }, [key, client, navigate])

  const copy = {
    checking: { title: 'Confirming your email…', lead: '' },
    verified: { title: 'Email confirmed', lead: 'Your address is confirmed. Sign in to continue.' },
    invalid: { title: "This link doesn't work", lead: 'It may have been used already or expired. Sign in to get a new one.' },
    offline: { title: "Couldn't reach Greenlit", lead: 'Check your connection and open the link again.' },
  }[state]

  return (
    <AuthLayout title={copy.title} lead={copy.lead || undefined}>
      {state !== 'checking' ? (
        <div className="auth-form">
          <Link className="btn btn-primary" to="/sign-in">
            Sign in
          </Link>
        </div>
      ) : null}
    </AuthLayout>
  )
}

export function RequestReset() {
  const { busy, run, formError } = useAuthForm()
  const [done, setDone] = useState(false)

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const r = await run('/auth/password/request', { email: new FormData(e.currentTarget).get('email') })
    // The same answer whether or not the address has an account.
    if (r && r.status < 500) setDone(true)
  }

  return (
    <AuthLayout
      title={done ? 'Check your email' : 'Reset your password'}
      lead={
        done
          ? 'If that address has a Greenlit account, a reset link is on its way. It works once, for 30 minutes.'
          : "Enter your email and we'll send you a link."
      }
      footer={<Link to="/sign-in">Back to sign in</Link>}
    >
      {done ? null : (
        <form className="auth-form" onSubmit={submit} noValidate>
          <FormError message={formError} />
          <Field label="Email" name="email" type="email" autoComplete="email" required />
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? 'Sending…' : 'Send reset link'}
          </Button>
        </form>
      )}
    </AuthLayout>
  )
}

export function ResetPassword() {
  const { key = '' } = useParams()
  const { busy, result, run, formError } = useAuthForm()
  const [done, setDone] = useState(false)

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const r = await run('/auth/password/reset', { key, password: new FormData(e.currentTarget).get('password') })
    if (r && (r.status === 200 || r.status === 401)) setDone(true)
  }

  if (done) {
    return (
      <AuthLayout title="Password changed" lead="Sign in with your new password.">
        <div className="auth-form">
          <Link className="btn btn-primary" to="/sign-in">
            Sign in
          </Link>
        </div>
      </AuthLayout>
    )
  }
  return (
    <AuthLayout title="Choose a new password" footer={<Link to="/sign-in">Back to sign in</Link>}>
      <form className="auth-form" onSubmit={submit} noValidate>
        <FormError message={formError ?? authError(result, 'key')} />
        <Field
          label="New password"
          name="password"
          type="password"
          autoComplete="new-password"
          required
          hint="At least 12 characters."
          error={authError(result, 'password')}
        />
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? 'Saving…' : 'Save new password'}
        </Button>
      </form>
    </AuthLayout>
  )
}

/** Owners and admins must set up an authenticator app before using an organisation. */
export function EnrolTotp() {
  const client = useQueryClient()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [setup, setSetup] = useState<{ secret: string; url: string } | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [codes, setCodes] = useState<string[] | null>(null)
  const { busy, result, run, formError } = useAuthForm()

  useEffect(() => {
    auth('/account/authenticators/totp')
      .then((r) => {
        const secret = r.meta.secret as string | undefined
        const url = r.meta.totp_url as string | undefined
        if (secret && url) setSetup({ secret, url })
        else if (r.status === 200) navigate(safeNext(params.get('next')), { replace: true }) // already enrolled
        else setLoadFailed(true)
      })
      .catch(() => setLoadFailed(true))
  }, [navigate, params])

  const qr = useMemo(() => (setup ? renderSVG(setup.url, { border: 0 }) : ''), [setup])

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const code = String(new FormData(e.currentTarget).get('code') ?? '').replace(/\s/g, '')
    const r = await run('/account/authenticators/totp', { code })
    if (r?.status === 200) {
      const rc = await auth('/account/authenticators/recovery-codes')
      const data = rc.data as { unused_codes?: string[] } | undefined
      setCodes(data?.unused_codes ?? [])
      await client.invalidateQueries({ queryKey: keys.me })
    }
  }

  if (codes) {
    return (
      <AuthLayout
        title="Save your recovery codes"
        lead="Each code works once, if you lose your phone. This is the only time they are shown."
      >
        <div className="auth-form">
          <div className="codes" aria-label="Recovery codes">
            {codes.map((c) => (
              <span key={c}>{c}</span>
            ))}
          </div>
          <Button variant="secondary" onClick={() => navigator.clipboard?.writeText(codes.join('\n'))}>
            Copy codes
          </Button>
          <Button variant="primary" onClick={() => navigate(safeNext(params.get('next')), { replace: true })}>
            I've saved them, continue
          </Button>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout
      title="Set up two-step verification"
      lead="Owners and admins need an authenticator app before they can use an organisation. Scan the code, then enter the 6 digits it shows."
    >
      {loadFailed ? (
        <FormError message="Couldn't start the setup. Sign in again and retry." />
      ) : !setup ? (
        <p className="faint">Preparing…</p>
      ) : (
        <form className="auth-form" onSubmit={submit} noValidate>
          <div className="qr" role="img" aria-label="QR code for your authenticator app" dangerouslySetInnerHTML={{ __html: qr }} />
          <p className="secret">
            Can't scan it? Enter this key: <span>{setup.secret}</span>
          </p>
          <FormError message={formError} />
          <Field
            label="Code from the app"
            name="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            required
            className="input input-code"
            error={authError(result, 'code')}
          />
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? 'Checking…' : 'Turn on two-step verification'}
          </Button>
        </form>
      )}
    </AuthLayout>
  )
}
