import { useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { serverMessage, useAddSource, useSources } from '../../api/queries'
import type { SourceRow } from '../../api/records'
import { useOrg } from '../../app/Gate'
import { Button } from '../../design/Button'
import { Mark } from '../../design/Mark'
import { Dialog } from '../../design/overlays'
import { EmptyState, ErrorState, SkeletonRows } from '../../design/states'
import { StatusChip } from '../../design/StatusChip'
import { ProjectNav } from '../projects/ProjectNav'
import { CAN_WRITE } from '../requirements/RequirementsList'
import '../defects/defects.css'
import '../plans/plans.css'
import './sources.css'

// Sources (UX screen 5, M2-01): the documents requirements are drafted from. Upload a PRD or
// paste its text; Greenlit reads it and drafts requirements for a person to review.

const when = (iso: string) =>
  new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

/** What is happening to a source right now, in the product's words. */
export function sourceStatus(s: SourceRow): string {
  if (s.state === 'failed') return s.failure || 'This document could not be read.'
  if (s.state === 'waiting') return 'Checking the file'
  if (s.state === 'parsing') return 'Reading the document'
  if (s.job?.running) return s.job.progress || 'Drafting requirements'
  if (s.job?.error) return s.job.error
  return `${s.pages} ${s.pages === 1 ? 'page' : 'pages'}`
}

export function SourcesList() {
  const { projectKey = '' } = useParams()
  const key = projectKey.toUpperCase()
  const base = `/${projectKey.toLowerCase()}/sources`
  const navigate = useNavigate()
  const { membership } = useOrg()
  const canWrite = CAN_WRITE.includes(membership.role)
  const sources = useSources(key)
  const add = useAddSource(key)
  const [pasting, setPasting] = useState(false)
  const picker = useRef<HTMLInputElement>(null)

  function upload(file: File | undefined) {
    if (file) add.mutate({ file }, { onSuccess: (made) => navigate(`${base}/${made.id}`) })
  }

  return (
    <div>
      <header className="page-head">
        <div>
          <p className="crumbs">
            <Link to="/projects">Projects</Link>
            <span aria-hidden="true">/</span>
            <span className="mono">{key}</span>
          </p>
          <h1 className="page-title">Sources</h1>
        </div>
        {canWrite ? (
          <div className="source-add">
            <Button onClick={() => setPasting(true)}>Paste text</Button>
            <Button variant="primary" disabled={add.isPending} onClick={() => picker.current?.click()}>
              {add.isPending ? 'Uploading…' : 'Upload a PRD'}
            </Button>
            <input
              ref={picker}
              type="file"
              hidden
              accept=".pdf,.docx,.md,.markdown,.txt"
              onChange={(e) => {
                upload(e.target.files?.[0])
                e.target.value = ''
              }}
            />
          </div>
        ) : null}
      </header>
      <ProjectNav projectKey={projectKey} />

      {canWrite ? (
        <p className="faint small source-notice">
          PDF, DOCX, Markdown or plain text, up to 20 MB and 200 pages. Use documents you are allowed to share: no real
          customer details.
        </p>
      ) : null}
      {add.isError ? (
        <p className="field-error" role="alert">
          {serverMessage(add.error) ?? "Couldn't add that document. Try again."}
        </p>
      ) : null}

      {sources.isPending ? (
        <SkeletonRows rows={4} />
      ) : sources.isError && !sources.data ? (
        <ErrorState message="Couldn't load the sources." onRetry={() => sources.refetch()} />
      ) : !sources.data.length ? (
        <EmptyState
          title="No source documents yet."
          actions={canWrite ? <Button onClick={() => setPasting(true)}>Paste a PRD</Button> : undefined}
        >
          Add a PRD and Greenlit drafts requirements from it. You review every draft before it counts.
        </EmptyState>
      ) : (
        <ul className="ledger defect-list">
          {sources.data.map((s) => (
            <li key={s.id} className="ledger-row">
              <span className="ledger-margin">
                <span>{s.accepted || ''}</span>
                <Mark kind={s.state === 'failed' ? 'fail' : s.drafts ? 'draft' : s.accepted ? 'pass' : 'open'} />
              </span>
              <Link to={`${base}/${s.id}`} className="ledger-body defect-row">
                <span className="defect-main">
                  <span className="defect-title">{s.title}</span>
                </span>
                <span className="defect-meta">
                  <span>{sourceStatus(s)}</span>
                  <span>
                    {s.pasted ? 'Pasted' : 'Uploaded'} {when(s.added_at)}
                    {s.added_by ? ` by ${s.added_by}` : ''}
                  </span>
                  {s.accepted ? <span>{s.accepted} accepted</span> : null}
                </span>
                <span className="defect-status">
                  {s.drafts ? (
                    <StatusChip status="draft" word={s.drafts === 1 ? '1 draft to review' : `${s.drafts} drafts to review`} />
                  ) : null}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <PasteDialog
        open={pasting}
        onOpenChange={setPasting}
        busy={add.isPending}
        error={add.isError ? (serverMessage(add.error) ?? "Couldn't add that text. Try again.") : null}
        onSubmit={(title, text) =>
          add.mutate({ title, text }, { onSuccess: (made) => navigate(`${base}/${made.id}`) })
        }
      />
    </div>
  )
}

function PasteDialog({
  open,
  onOpenChange,
  busy,
  error,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  busy: boolean
  error: string | null
  onSubmit: (title: string, text: string) => void
}) {
  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    onSubmit(String(form.get('title') ?? '').trim(), String(form.get('text') ?? ''))
  }
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Paste a PRD"
      description="Greenlit reads the text and drafts requirements from it. Nothing counts until you accept it."
      width={640}
    >
      <form onSubmit={submit} className="dialog-form">
        <div className="field">
          <label className="field-label" htmlFor="source-title">
            Title
          </label>
          <input className="input" id="source-title" name="title" required maxLength={200} placeholder="Checkout PRD v3" autoFocus />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="source-text">
            Text
          </label>
          <textarea className="textarea" id="source-text" name="text" rows={12} required />
          <span className="field-hint">Markdown headings (#) are kept as sections. Use test data only.</span>
        </div>
        {error ? (
          <p className="field-error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="dialog-actions">
          <Button variant="quiet" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? 'Reading…' : 'Add and draft requirements'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
