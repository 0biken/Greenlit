import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { serverMessage, useCreateRequirement, useEditRequirement, useRequirement } from '../../api/queries'
import type { RequirementDetail, Severity } from '../../api/records'
import { Button } from '../../design/Button'
import { IdTag } from '../../design/IdTag'
import { ErrorState, SkeletonRows } from '../../design/states'
import { StatusChip } from '../../design/StatusChip'
import { SEVERITY_WORD as PRIORITY_WORD } from '../defects/DefectsList'
import { NotFound } from '../NotFound'
import { ProjectNav } from '../projects/ProjectNav'
import '../defects/defects.css'
import '../plans/plans.css'

// One requirement (M2-08): its text, the cases that cover it, and its earlier texts. Changing
// the text raises the revision, which marks those cases Stale until someone reviews them.

const when = (iso: string) =>
  new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

type Values = { title: string; text: string; priority: Severity }

function RequirementForm({
  initial,
  busy,
  error,
  submitLabel,
  note,
  onSubmit,
  onCancel,
}: {
  initial?: Values
  busy: boolean
  error: string | null
  submitLabel: string
  note?: string
  onSubmit: (values: Values) => void
  onCancel: () => void
}) {
  const [priority, setPriority] = useState<Severity>(initial?.priority ?? 'medium')

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    onSubmit({
      title: String(form.get('title') ?? '').trim(),
      text: String(form.get('text') ?? '').trim(),
      priority,
    })
  }

  return (
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
          defaultValue={initial?.title}
          placeholder="Pay by saved card"
          autoFocus
        />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="text">
          What must be true
        </label>
        <textarea
          className="textarea"
          id="text"
          name="text"
          rows={6}
          required
          defaultValue={initial?.text}
          placeholder="A signed-in shopper can pay with a card saved on their account."
        />
        {note ? <span className="field-hint">{note}</span> : null}
      </div>
      <fieldset className="segmented">
        <legend className="field-label">Priority</legend>
        {(Object.keys(PRIORITY_WORD) as Severity[]).map((p) => (
          <label key={p} className="segment">
            <input type="radio" name="priority" checked={priority === p} onChange={() => setPriority(p)} />
            <span>{PRIORITY_WORD[p]}</span>
          </label>
        ))}
      </fieldset>
      {error ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="form-actions">
        <Button variant="quiet" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={busy}>
          {submitLabel}
        </Button>
      </div>
    </form>
  )
}

export function NewRequirementPage() {
  const { projectKey = '' } = useParams()
  const key = projectKey.toUpperCase()
  const base = `/${projectKey.toLowerCase()}`
  const navigate = useNavigate()
  const create = useCreateRequirement(key)

  return (
    <div>
      <header className="page-head">
        <div>
          <p className="crumbs">
            <Link to={base} className="mono">
              {key}
            </Link>
            <span aria-hidden="true">/</span>
            <Link to={`${base}/requirements`}>Requirements</Link>
          </p>
          <h1 className="page-title">Add a requirement</h1>
        </div>
      </header>
      <ProjectNav projectKey={projectKey} />
      <RequirementForm
        busy={create.isPending}
        submitLabel={create.isPending ? 'Adding…' : 'Add requirement'}
        error={
          create.isError
            ? (serverMessage(create.error) ?? "Couldn't add the requirement. Check the fields and try again.")
            : null
        }
        onCancel={() => navigate(`${base}/requirements`)}
        onSubmit={(values) =>
          create.mutate(values, {
            onSuccess: (made) => navigate(`${base}/requirements/${made.number}`, { replace: true }),
          })
        }
      />
    </div>
  )
}

export function RequirementPage() {
  const { projectKey = '', no = '' } = useParams()
  const key = projectKey.toUpperCase()
  const requirement = useRequirement(key, no)

  if (requirement.error instanceof ApiError && requirement.error.isNotFound) return <NotFound />
  if (requirement.isPending) return <SkeletonRows rows={6} />
  if (requirement.isError) {
    return <ErrorState message="Couldn't load this requirement." onRetry={() => requirement.refetch()} />
  }
  return <RequirementRecord key={requirement.data.id} projectKey={projectKey} requirement={requirement.data} />
}

function RequirementRecord({ projectKey, requirement: r }: { projectKey: string; requirement: RequirementDetail }) {
  const key = projectKey.toUpperCase()
  const base = `/${projectKey.toLowerCase()}`
  const edit = useEditRequirement(key, String(r.number))
  const [editing, setEditing] = useState(false)
  const earlier = r.revisions.filter((v) => v.revision !== r.revision)

  return (
    <div className="defect">
      <header className="page-head">
        <div>
          <p className="crumbs">
            <Link to={base} className="mono">
              {key}
            </Link>
            <span aria-hidden="true">/</span>
            <Link to={`${base}/requirements`}>Requirements</Link>
          </p>
          <h1 className="page-title defect-heading">
            <IdTag id={r.display_id} /> {r.title}
          </h1>
          <p className="page-sub defect-facts">
            {!r.covered ? (
              <StatusChip status="uncovered" />
            ) : r.stale_cases ? (
              <StatusChip status="stale" word={r.stale_cases === 1 ? '1 stale case' : `${r.stale_cases} stale cases`} />
            ) : (
              <span>Covered</span>
            )}
            <span>{PRIORITY_WORD[r.priority]} priority</span>
            <span>Revision {r.revision}</span>
            {r.created_by ? <span>Added by {r.created_by}</span> : null}
          </p>
        </div>
        {r.actions.edit && !editing ? <Button onClick={() => setEditing(true)}>Edit</Button> : null}
      </header>
      <ProjectNav projectKey={projectKey} />

      {editing ? (
        <RequirementForm
          initial={{ title: r.title, text: r.text, priority: r.priority }}
          busy={edit.isPending}
          submitLabel={edit.isPending ? 'Saving…' : 'Save changes'}
          note={
            r.cases
              ? `Changing this text marks ${r.cases === 1 ? 'the 1 case' : `the ${r.cases} cases`} written against it as Stale.`
              : undefined
          }
          error={edit.isError ? (serverMessage(edit.error) ?? "Couldn't save the changes. Try again.") : null}
          onCancel={() => setEditing(false)}
          onSubmit={(values) => edit.mutate(values, { onSuccess: () => setEditing(false) })}
        />
      ) : (
        <div className="defect-layout">
          <div className="defect-record">
            <section className="defect-field">
              <h2 className="overline">What must be true</h2>
              <p className="pre">{r.text}</p>
            </section>
            <h2 className="dash-h">Test cases</h2>
            {r.linked_cases.length ? (
              <ul className="plain-list">
                {r.linked_cases.map((c) => (
                  <li key={c.display_id} className="link-row">
                    <IdTag id={c.display_id} to={`${base}/cases/${c.number}`} />
                    <span className="link-row-title">{c.title}</span>
                    {c.stale ? <StatusChip status="stale" /> : null}
                    <Link className="faint small" to={`${base}/plans/${c.plan_no}`}>
                      {c.plan}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="faint">
                No accepted case in a published plan covers this yet. <Link to={`${base}/plans`}>Open the plans</Link>
              </p>
            )}
          </div>
          <aside className="defect-side">
            <h2 className="dash-h">History</h2>
            <ul className="history-list">
              {r.history.map((h, i) => (
                <li key={i}>
                  <span className="faint small">{when(h.at)}</span> {h.actor} {h.text}
                </li>
              ))}
            </ul>
            {earlier.length ? (
              <>
                <h2 className="dash-h">Earlier text</h2>
                {earlier.map((v) => (
                  <details key={v.revision} className="earlier-text">
                    <summary>
                      Revision {v.revision} <span className="faint small">until {when(r.revisions.find((x) => x.revision === v.revision + 1)?.at ?? v.at)}</span>
                    </summary>
                    <p className="pre">{v.text}</p>
                  </details>
                ))}
              </>
            ) : null}
          </aside>
        </div>
      )}
    </div>
  )
}
