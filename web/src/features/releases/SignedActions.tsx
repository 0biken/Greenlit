import { useState } from 'react'
import {
  downloadReportPdf,
  serverMessage,
  useCreateShareLink,
  useRevokeShareLink,
  useShareLinks,
} from '../../api/queries'
import { Button } from '../../design/Button'

// After sign-off: download the frozen report as a PDF, and share a read-only link to it
// (FR-RPT-04). A link's address is shown once, when it is made; it can be revoked and expires.

const day = (iso: string) => new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
const STATE = { active: 'Active', expired: 'Expired', revoked: 'Revoked' } as const

export function SignedActions({ projectKey, version, canShare }: { projectKey: string; version: string; canShare: boolean }) {
  const links = useShareLinks(projectKey, version, canShare)
  const create = useCreateShareLink(projectKey, version)
  const revoke = useRevokeShareLink(projectKey, version)
  const [downloading, setDownloading] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const address = create.data ? `${window.location.origin}/shared/${create.data.token}` : null

  async function pdf() {
    setProblem(null)
    setDownloading(true)
    try {
      await downloadReportPdf(projectKey, version)
    } catch {
      setProblem("Couldn't download the PDF. Try again.")
    } finally {
      setDownloading(false)
    }
  }

  async function share() {
    setProblem(null)
    setCopied(false)
    try {
      const made = await create.mutateAsync()
      await copy(`${window.location.origin}/shared/${made.token}`)
    } catch (error) {
      setProblem(serverMessage(error) ?? "Couldn't make a share link. Try again.")
    }
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
    } catch {
      setCopied(false) // the address is on screen to copy by hand
    }
  }

  return (
    <div className="signed-actions">
      <div className="sign-actions">
        <Button onClick={pdf} disabled={downloading}>
          {downloading ? 'Preparing…' : 'Download PDF'}
        </Button>
        {canShare ? (
          <Button onClick={share} disabled={create.isPending}>
            {create.isPending ? 'Making link…' : 'Copy share link'}
          </Button>
        ) : null}
      </div>
      {problem ? (
        <p className="field-error" role="alert">
          {problem}
        </p>
      ) : null}

      {address && create.data ? (
        <div className="share-new" role="status">
          <label className="field-label" htmlFor="share-address">
            {copied ? 'Link copied.' : 'New link.'} Anyone with it can read the signed report until{' '}
            {day(create.data.expires_at)}.
          </label>
          <div className="share-address">
            <input
              id="share-address"
              className="input mono"
              readOnly
              value={address}
              onFocus={(e) => e.target.select()}
            />
            <Button size="sm" onClick={() => copy(address)}>
              Copy
            </Button>
          </div>
          <p className="faint small">This address is shown only now. If you lose it, make a new link.</p>
        </div>
      ) : null}

      {canShare && links.data?.length ? (
        <ul className="share-list" aria-label="Share links">
          {links.data.map((link) => (
            <li key={link.id}>
              <span>
                <strong>{STATE[link.state]}</strong>{' '}
                <span className="faint">
                  made {day(link.created_at)}
                  {link.created_by ? ` by ${link.created_by}` : ''}, {link.state === 'active' ? 'expires' : 'expiry'}{' '}
                  {day(link.expires_at)}
                </span>
              </span>
              {link.state === 'active' ? (
                <Button size="sm" variant="danger" disabled={revoke.isPending} onClick={() => revoke.mutate(link.id)}>
                  Revoke
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
