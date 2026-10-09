import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { ApiError, api, setCurrentOrg } from '../../api/client'
import { keys } from '../../api/queries'
import { Button } from '../../design/Button'
import { AuthLayout, Field, FormError } from '../auth/AuthLayout'
import { useSignOut } from '../auth/session'

type Created = { id: string; slug: string; name: string }

function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || !error.body || typeof error.body !== 'object') return {}
  return Object.fromEntries(
    Object.entries(error.body as Record<string, unknown>).map(([k, v]) => [k, Array.isArray(v) ? String(v[0]) : String(v)]),
  )
}

/** First visit with no organisation: create one (the creator becomes its owner). */
export function Welcome() {
  const client = useQueryClient()
  const navigate = useNavigate()
  const signOut = useSignOut()
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setBusy(true)
    setErrors({})
    try {
      const org = await api<Created>('/api/orgs/', {
        method: 'POST',
        noOrg: true,
        body: { name: new FormData(e.currentTarget).get('name') },
      })
      setCurrentOrg(org.slug)
      await client.invalidateQueries({ queryKey: keys.me })
      navigate('/inbox', { replace: true })
    } catch (error) {
      const fields = fieldErrors(error)
      setErrors(Object.keys(fields).length ? fields : { form: "Couldn't create the organisation. Try again." })
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      title="Set up your organisation"
      lead="Your team's projects, people and records live here. If you were invited, open the link in your invitation email instead."
      footer={
        <button type="button" className="link-button" onClick={signOut}>
          Sign out
        </button>
      }
    >
      <form className="auth-form" onSubmit={submit} noValidate>
        <FormError message={errors.form ?? errors.detail} />
        <Field label="Organisation name" name="name" required autoFocus placeholder="Karma Groups" error={errors.name} />
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? 'Creating…' : 'Create organisation'}
        </Button>
      </form>
    </AuthLayout>
  )
}

/** /invite/:token from the invitation email. Every failure gives the same answer (M1-08). */
export function AcceptInvite() {
  const { token = '' } = useParams()
  const client = useQueryClient()
  const navigate = useNavigate()
  const [state, setState] = useState<'joining' | 'failed'>('joining')
  const sent = useRef(false)

  useEffect(() => {
    if (sent.current) return
    sent.current = true
    api<Created>('/api/invites/accept/', { method: 'POST', noOrg: true, body: { token } })
      .then(async (org) => {
        setCurrentOrg(org.slug)
        await client.invalidateQueries({ queryKey: keys.me })
        navigate('/inbox', { replace: true })
      })
      .catch(() => setState('failed'))
  }, [token, client, navigate])

  if (state === 'joining') return <AuthLayout title="Joining the organisation…">{null}</AuthLayout>
  return (
    <AuthLayout
      title="This invitation can't be used"
      lead="It may have expired, been used already, or been sent to a different email address than the one you signed in with. Ask whoever invited you for a new link."
    >
      <div className="auth-form">
        <Link className="btn btn-secondary" to="/inbox">
          Go to Greenlit
        </Link>
      </div>
    </AuthLayout>
  )
}
