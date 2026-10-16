import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { serverMessage, useDraftCase, usePlan, usePlanVersion, useRequirements } from '../../api/queries'
import type { PlanCase, Severity } from '../../api/records'
import { Button } from '../../design/Button'
import { IdTag } from '../../design/IdTag'
import { ErrorState, SkeletonRows } from '../../design/states'
import { StatusChip } from '../../design/StatusChip'
import { SEVERITY_WORD as PRIORITY_WORD } from '../defects/DefectsList'
import { NotFound } from '../NotFound'
import { ProjectNav } from '../projects/ProjectNav'
import '../defects/defects.css'
import './plans.css'

// The draft editor (M3-02, M3-10). Cases on the left in run order; the case being written on
// the right. Saving a case never changes a published version: it changes the draft only.

type Selected = number | 'new'

export function PlanEditor() {
  const { projectKey = '', no = '' } = useParams()
  const key = projectKey.toUpperCase()
  const base = `/${projectKey.toLowerCase()}`
  const here = `${base}/plans/${no}`
  const plan = usePlan(key, no)
  const hasDraft = Boolean(plan.data?.draft)
  const draft = usePlanVersion(key, no, 'draft', hasDraft)
  const change = useDraftCase(key, no)
  const [selected, setSelected] = useState<Selected | null>(null)

  if (plan.error instanceof ApiError && plan.error.isNotFound) return <NotFound />
  if (plan.isPending || (hasDraft && draft.isPending)) return <SkeletonRows rows={6} />
  if (plan.isError) return <ErrorState message="Couldn't load this plan." onRetry={() => plan.refetch()} />

  const cases = draft.data?.cases ?? []
  const current = selected === 'new' ? null : (cases.find((c) => c.number === selected) ?? null)
  const editing: Selected | null = selected === 'new' ? 'new' : current ? current.number : null

  function move(c: PlanCase, to: number) {
    change.mutate({ do: 'edit', case: c.number, body: { position: to } })
  }

  return (
    <div className="defect">
      <header className="page-head">
        <div>
          <p className="crumbs">
            <Link to={base} className="mono">
              {key}
            </Link>
            <span aria-hidden="true">/</span>
            <Link to={`${base}/plans`}>Test plans</Link>
            <span aria-hidden="true">/</span>
            <Link to={here}>{plan.data.display_id}</Link>
          </p>
          <h1 className="page-title defect-heading">
            {plan.data.title} <StatusChip status="draft" />
          </h1>
          <p className="page-sub">
            {plan.data.version
              ? `Changes stay in the draft. Version ${plan.data.version} is used for runs until a lead approves this.`
              : 'Add the cases, then submit the plan for a lead to approve.'}
          </p>
        </div>
        <Link className="btn btn-primary" to={here}>
          Done
        </Link>
      </header>
      <ProjectNav projectKey={projectKey} />

      {!hasDraft ? (
        <p className="faint">
          This plan has no draft open. <Link to={here}>Go back to the plan</Link> and choose Edit plan.
        </p>
      ) : !plan.data.actions.edit ? (
        <p className="faint">
          You can read this draft on <Link to={`${here}?v=draft`}>the plan page</Link>, but your role cannot change it.
        </p>
      ) : (
        <div className="editor-layout">
          <div>
            <ol className="editor-cases" aria-label="Cases in the draft">
              {cases.map((c, i) => (
                <li key={c.case} className="editor-case" data-on={editing === c.number || undefined}>
                  <button type="button" className="editor-case-main" onClick={() => setSelected(c.number)}>
                    <IdTag id={c.case} />
                    <span className="editor-case-title">{c.title}</span>
                  </button>
                  <span className="editor-case-tools">
                    <button
                      type="button"
                      className="icon-button"
                      aria-label={`Move ${c.case} up`}
                      disabled={i === 0 || change.isPending}
                      onClick={() => move(c, i)}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label={`Move ${c.case} down`}
                      disabled={i === cases.length - 1 || change.isPending}
                      onClick={() => move(c, i + 2)}
                    >
                      ↓
                    </button>
                  </span>
                </li>
              ))}
            </ol>
            <Button onClick={() => setSelected('new')} disabled={editing === 'new'}>
              Add a case
            </Button>
          </div>

          <div>
            {editing === null ? (
              <p className="faint">
                {cases.length ? 'Choose a case to edit it, or add a new one.' : 'This draft has no cases yet. Add the first one.'}
              </p>
            ) : (
              <CaseForm
                // A fresh form for each case, so one case's typing never leaks into another.
                key={editing === 'new' ? `new-${cases.length}` : `${editing}-${current?.revision}`}
                projectKey={projectKey}
                item={current}
                busy={change.isPending}
                error={change.isError ? (serverMessage(change.error) ?? "Couldn't save the case. Try again.") : null}
                onSave={(body) =>
                  change.mutate(
                    current ? { do: 'edit', case: current.number, body } : { do: 'add', body },
                    { onSuccess: () => setSelected(null) },
                  )
                }
                onRemove={
                  current
                    ? () => change.mutate({ do: 'remove', case: current.number }, { onSuccess: () => setSelected(null) })
                    : undefined
                }
                onCancel={() => setSelected(null)}
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export type CaseBody = {
  title: string
  preconditions: string
  steps: string[]
  expected: string
  priority: Severity
  requirements: number[]
}

export function CaseForm({
  projectKey,
  item,
  busy,
  error,
  saveLabel,
  onSave,
  onRemove,
  onCancel,
}: {
  projectKey: string
  item: PlanCase | null
  busy: boolean
  error: string | null
  /** The save button's words, where "Save case" would mislead. */
  saveLabel?: string
  onSave: (body: CaseBody) => void
  onRemove?: () => void
  onCancel: () => void
}) {
  const requirements = useRequirements(projectKey.toUpperCase())
  const [priority, setPriority] = useState<Severity>(item?.priority ?? 'medium')
  const [linked, setLinked] = useState<number[]>(() => item?.requirements.map((r) => r.number) ?? [])
  const stale = item?.requirements.filter((r) => r.stale) ?? []
  const choices = (requirements.data ?? []).filter((r) => r.review_state === 'accepted' || linked.includes(r.number))

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    const text = (name: string) => String(form.get(name) ?? '').trim()
    onSave({
      title: text('title'),
      preconditions: text('preconditions'),
      steps: text('steps')
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean),
      expected: text('expected'),
      priority,
      requirements: linked,
    })
  }

  return (
    <form className="case-form" onSubmit={submit}>
      <h2 className="dash-h">{item ? <IdTag id={item.case} /> : 'New case'}</h2>
      {stale.length ? (
        <p className="stale-note" role="status">
          <StatusChip status="stale" word="Requirement changed" /> {stale.map((r) => r.display_id).join(', ')}{' '}
          {stale.length === 1 ? 'has' : 'have'} new text since this case was written. Check the steps still hold, then
          save: saving records that you reviewed it.
        </p>
      ) : null}
      <div className="field">
        <label className="field-label" htmlFor="case-title">
          Title
        </label>
        <input
          className="input"
          id="case-title"
          name="title"
          required
          maxLength={200}
          defaultValue={item?.title}
          placeholder="Pays with a saved card"
          autoFocus
        />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="case-pre">
          Before you start <span className="faint">(optional)</span>
        </label>
        <textarea className="textarea" id="case-pre" name="preconditions" rows={2} defaultValue={item?.preconditions} />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="case-steps">
          Steps
        </label>
        <textarea
          className="textarea"
          id="case-steps"
          name="steps"
          rows={6}
          required
          defaultValue={item?.steps.join('\n')}
          placeholder={'Sign in as [shopper with a saved card]\nAdd any item to the basket\nPay with the saved card'}
        />
        <span className="field-hint">One step per line, one action each. They are numbered for you.</span>
      </div>
      <div className="field">
        <label className="field-label" htmlFor="case-expected">
          Expected result
        </label>
        <textarea
          className="textarea"
          id="case-expected"
          name="expected"
          rows={2}
          required
          defaultValue={item?.expected}
          placeholder="The order is confirmed and the card is charged once."
        />
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
      <fieldset className="req-picker">
        <legend className="field-label">Requirements this case covers</legend>
        {requirements.isPending ? (
          <p className="faint small">Loading…</p>
        ) : !choices.length ? (
          <p className="faint small">
            No requirements on this project yet.{' '}
            <Link to={`/${projectKey.toLowerCase()}/requirements/new`}>Add one</Link>
          </p>
        ) : (
          choices.map((r) => (
            <label key={r.number} className="check-row">
              <input
                type="checkbox"
                checked={linked.includes(r.number)}
                onChange={(e) =>
                  setLinked((l) => (e.target.checked ? [...l, r.number] : l.filter((n) => n !== r.number)))
                }
              />
              <span>
                <span className="id">{r.display_id}</span> {r.title}
              </span>
            </label>
          ))
        )}
      </fieldset>
      {error ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="form-actions">
        {onRemove ? (
          <Button variant="danger" disabled={busy} onClick={onRemove}>
            Remove from plan
          </Button>
        ) : null}
        <Button variant="quiet" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? 'Saving…' : (saveLabel ?? (item ? 'Save case' : 'Add case'))}
        </Button>
      </div>
    </form>
  )
}
