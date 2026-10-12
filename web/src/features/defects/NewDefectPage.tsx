import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'
import { serverMessage, useCreateDefect, useProjectMembers } from '../../api/queries'
import type { Severity } from '../../api/records'
import { Button } from '../../design/Button'
import { IdTag } from '../../design/IdTag'
import { ProjectNav } from '../projects/ProjectNav'
import { SEVERITY_WORD } from './DefectsList'
import './defects.css'

// File a defect (FR-DEF-01). Opened from a failed result in a run it arrives pre-filled with
// that case's steps and expected result, and stays linked to the run and case (FR-RUN-04).

export type DefectPrefill = {
  resultId: string
  run: string
  caseId: string
  title: string
  steps: string
  expected: string
  actual: string
  release: string
}

export function NewDefectPage() {
  const { projectKey = '' } = useParams()
  const key = projectKey.toUpperCase()
  const navigate = useNavigate()
  const prefill = (useLocation().state as { prefill?: DefectPrefill } | null)?.prefill
  const members = useProjectMembers(key)
  const create = useCreateDefect(key)
  const [files, setFiles] = useState<File[]>([])
  const [severity, setSeverity] = useState<Severity>('medium')
  const base = `/${projectKey.toLowerCase()}`

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    const text = (name: string) => String(form.get(name) ?? '').trim()
    try {
      const made = await create.mutateAsync({
        title: text('title'),
        steps: text('steps'),
        expected: text('expected'),
        actual: text('actual'),
        severity,
        owner_id: text('owner') || null,
        release: prefill?.release || null,
        found_in_result: prefill?.resultId ?? null,
        files,
      })
      navigate(`${base}/bugs/${made.display_id.split('-')[1]}`, { replace: true })
    } catch {
      // shown below from create.error
    }
  }

  return (
    <div>
      <header className="page-head">
        <div>
          <p className="crumbs">
            <Link to={base} className="mono">
              {key}
            </Link>
            <span aria-hidden="true">/</span>
            <Link to={`${base}/bugs`}>Defects</Link>
          </p>
          <h1 className="page-title">File a defect</h1>
          {prefill ? (
            <p className="page-sub">
              Found in <IdTag id={prefill.run} /> on <IdTag id={prefill.caseId} />. Its evidence comes with it.
            </p>
          ) : null}
        </div>
      </header>
      <ProjectNav projectKey={projectKey} />

      <form className="defect-form" onSubmit={submit}>
        <div className="field">
          <label className="field-label" htmlFor="title">
            Title
          </label>
          <input
            className="input"
            id="title"
            name="title"
            required
            maxLength={200}
            defaultValue={prefill?.title}
            placeholder="Payment times out on card checkout"
            autoFocus
          />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="steps">
            Steps to reproduce
          </label>
          <textarea className="textarea" id="steps" name="steps" rows={5} defaultValue={prefill?.steps} />
        </div>
        <div className="form-pair">
          <div className="field">
            <label className="field-label" htmlFor="expected">
              Expected
            </label>
            <textarea className="textarea" id="expected" name="expected" defaultValue={prefill?.expected} />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="actual">
              Actual
            </label>
            <textarea className="textarea" id="actual" name="actual" defaultValue={prefill?.actual} />
          </div>
        </div>
        <div className="form-pair">
          <fieldset className="segmented">
            <legend className="field-label">Severity</legend>
            {(Object.keys(SEVERITY_WORD) as Severity[]).map((s) => (
              <label key={s} className="segment">
                <input type="radio" name="severity" checked={severity === s} onChange={() => setSeverity(s)} />
                <span>{SEVERITY_WORD[s]}</span>
              </label>
            ))}
          </fieldset>
          <div className="field">
            <label className="field-label" htmlFor="owner">
              Owner
            </label>
            <select className="input" id="owner" name="owner" defaultValue="">
              <option value="">No owner yet</option>
              {members.data?.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.name || m.email}
                </option>
              ))}
            </select>
            <span className="field-hint">The person who retests it once it is fixed.</span>
          </div>
        </div>
        <div className="field">
          <span className="field-label">Evidence</span>
          <label className="dropzone">
            <input
              type="file"
              accept="image/*,video/*,.pdf,.txt,.log,.har"
              multiple
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            />
            {files.length ? (
              <span>
                {files.length === 1 ? files[0].name : `${files.length} files`} chosen. <u>Change</u>
              </span>
            ) : (
              <span>
                <u>Choose screenshots, recordings or logs</u>. Use test data only: no real customer details.
              </span>
            )}
          </label>
        </div>
        {create.isError ? (
          <p className="field-error" role="alert">
            {serverMessage(create.error) ?? "Couldn't file the defect. Check the fields and try again."}
          </p>
        ) : null}
        <div className="form-actions">
          <Link className="btn btn-quiet" to={`${base}/bugs`}>
            Cancel
          </Link>
          <Button type="submit" variant="primary" disabled={create.isPending}>
            {create.isPending ? 'Filing…' : 'File defect'}
          </Button>
        </div>
      </form>
    </div>
  )
}
