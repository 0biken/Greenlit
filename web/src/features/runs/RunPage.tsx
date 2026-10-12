import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { attachResultEvidence, serverMessage, useCompleteRun, useRun } from '../../api/queries'
import type { EvidenceFile, Outcome, RunCase, RunDetail } from '../../api/records'
import { useOrg } from '../../app/Gate'
import { useHotkeys } from '../../app/hotkeys'
import { Button } from '../../design/Button'
import { IdTag } from '../../design/IdTag'
import { Mark, type MarkKind } from '../../design/Mark'
import { ErrorState, SkeletonRows } from '../../design/states'
import { StatusChip, type Status } from '../../design/StatusChip'
import { EvidenceList } from '../defects/EvidenceList'
import type { DefectPrefill } from '../defects/NewDefectPage'
import { NotFound } from '../NotFound'
import { ProjectNav } from '../projects/ProjectNav'
import { useOutbox, type Pending, type SaveState } from './outbox'
import './runs.css'

// The run screen (M4-04, UX Flow 2). Cases on the left, the current case on the right.
// P F B N record the outcome, E attaches evidence, arrows move. Nothing here animates:
// these keys are pressed hundreds of times a day.

const OUTCOMES: { id: Outcome; key: string; word: string; mark: MarkKind; status: Status }[] = [
  { id: 'passed', key: 'P', word: 'Passed', mark: 'pass', status: 'passed' },
  { id: 'failed', key: 'F', word: 'Failed', mark: 'fail', status: 'failed' },
  { id: 'blocked', key: 'B', word: 'Blocked', mark: 'hold', status: 'blocked' },
  { id: 'not_run', key: 'N', word: 'Not run', mark: 'open', status: 'not_run' },
]
const BY_ID = Object.fromEntries(OUTCOMES.map((o) => [o.id, o])) as Record<Outcome, (typeof OUTCOMES)[number]>
const CAN_TEST = ['owner', 'admin', 'qa_lead', 'qa_engineer']

export function RunPage() {
  const { projectKey = '', no = '' } = useParams()
  const key = projectKey.toUpperCase()
  const run = useRun(key, no)

  if (run.error instanceof ApiError && run.error.isNotFound) return <NotFound />
  if (run.isPending) {
    return (
      <div>
        <header className="page-head">
          <h1 className="page-title">Run {no}</h1>
        </header>
        <SkeletonRows rows={6} />
      </div>
    )
  }
  if (run.isError) return <ErrorState message="Couldn't load this run." onRetry={() => run.refetch()} />
  // Keyed by the run, so local state starts clean when moving between runs.
  return <RunScreen key={run.data.number} projectKey={projectKey} run={run.data} />
}

function RunScreen({ projectKey, run }: { projectKey: string; run: RunDetail }) {
  const key = projectKey.toUpperCase()
  const base = `/${projectKey.toLowerCase()}`
  const navigate = useNavigate()
  const { membership } = useOrg()
  const complete = useCompleteRun(key, run.number)
  const [done, setDone] = useState(run.state === 'complete')
  const editable = !done && CAN_TEST.includes(membership.role)

  // What the tester has recorded here, laid over what the server last sent: first what is
  // still waiting to be sent, then what this visit has saved. A result the server refused is
  // in neither, so the case goes back to showing what is actually stored.
  const [saved, setSaved] = useState<Record<string, Pending>>({})
  const [evidence, setEvidence] = useState<Record<string, EvidenceFile[]>>({})
  const [uploading, setUploading] = useState<Record<string, number>>({})
  const [problem, setProblem] = useState<string | null>(null)
  const [announce, setAnnounce] = useState('')
  const [cursor, setCursor] = useState(() => Math.max(run.cases.findIndex((c) => c.outcome === 'not_run'), 0))
  const rowRefs = useRef<(HTMLLIElement | null)[]>([])
  const fileInput = useRef<HTMLInputElement>(null)

  const outbox = useOutbox(key, run.number, (resultId, value) => {
    setSaved((s) => ({ ...s, [resultId]: value }))
    const c = run.cases.find((x) => x.result_id === resultId)
    if (c) setAnnounce(`${c.case} saved as ${BY_ID[value.outcome].word}.`)
  })

  const cases = useMemo(
    () =>
      run.cases.map((c) => {
        const mine = outbox.pending[c.result_id] ?? saved[c.result_id]
        return {
          ...c,
          outcome: mine?.outcome ?? c.outcome,
          note: mine?.note ?? c.note,
          evidence: [...c.evidence, ...(evidence[c.result_id] ?? [])],
        }
      }),
    [run.cases, saved, outbox.pending, evidence],
  )
  const current = cases[cursor]
  const counts = Object.fromEntries(OUTCOMES.map((o) => [o.id, cases.filter((c) => c.outcome === o.id).length]))

  function setOutcome(outcome: Outcome, note?: string) {
    if (!editable || !current) return
    outbox.record(current.result_id, { outcome, note: note ?? current.note })
  }

  function move(delta: number) {
    const next = Math.min(Math.max(cursor + delta, 0), cases.length - 1)
    setCursor(next)
    rowRefs.current[next]?.scrollIntoView({ block: 'nearest' })
  }

  const attach = useCallback(
    async (target: RunCase, files: File[]) => {
      if (!files.length) return
      setProblem(null)
      setUploading((u) => ({ ...u, [target.result_id]: (u[target.result_id] ?? 0) + files.length }))
      try {
        const made = await attachResultEvidence(key, run.number, target.result_id, files)
        setEvidence((e) => ({ ...e, [target.result_id]: [...(e[target.result_id] ?? []), ...made] }))
        setAnnounce(`${made.length === 1 ? 'Evidence' : `${made.length} files`} attached to ${target.case}.`)
      } catch (error) {
        setProblem(serverMessage(error) ?? `Couldn't attach evidence to ${target.case}. Try again.`)
      } finally {
        setUploading((u) => ({ ...u, [target.result_id]: Math.max((u[target.result_id] ?? 0) - files.length, 0) }))
      }
    },
    [key, run.number],
  )

  // Paste a screenshot anywhere on the page to attach it to the current case (FR-RUN-03).
  useEffect(() => {
    if (!editable || !current) return
    function onPaste(e: ClipboardEvent) {
      const files = Array.from(e.clipboardData?.files ?? [])
      if (!files.length) return
      e.preventDefault()
      void attach(current, files)
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [attach, current, editable])

  useHotkeys(
    {
      p: () => setOutcome('passed'),
      f: () => setOutcome('failed'),
      b: () => setOutcome('blocked'),
      n: () => setOutcome('not_run'),
      e: () => editable && fileInput.current?.click(),
      ArrowDown: () => move(1),
      ArrowUp: () => move(-1),
      j: () => move(1),
      k: () => move(-1),
    },
    cases.length > 0,
  )

  async function finish() {
    setProblem(null)
    try {
      await complete.mutateAsync()
      setDone(true)
      setAnnounce(`${run.display_id} is complete.`)
    } catch {
      // The list of what is missing is shown from complete.error.
    }
  }

  function fileDefect(c: RunCase) {
    const prefill: DefectPrefill = {
      resultId: c.result_id,
      run: run.display_id,
      caseId: c.case,
      title: c.title,
      steps: c.steps.map((s, i) => `${i + 1}. ${s}`).join('\n'),
      expected: c.expected,
      actual: c.note,
      release: run.release,
    }
    navigate(`${base}/bugs/new`, { state: { prefill } })
  }

  const missing =
    complete.error instanceof ApiError
      ? ((complete.error.body as { missing?: { result_id: string; case: string; title: string }[] })?.missing ?? [])
      : []
  const unsaved = Object.values(outbox.states).some((s) => s === 'saving' || s === 'waiting')

  return (
    <div className="run">
      <header className="page-head">
        <div>
          <p className="crumbs">
            <Link to={base} className="mono">
              {key}
            </Link>
            <span aria-hidden="true">/</span>
            <Link to={`${base}/runs`}>Runs</Link>
          </p>
          <h1 className="page-title">
            <span className="mono-title">{run.display_id}</span> {run.plan}{' '}
            <span className="run-version mono">v{run.plan_version}</span>
          </h1>
          <p className="page-sub run-facts">
            <span>
              Release{' '}
              <Link to={`${base}/releases/${run.release}`} className="mono">
                {run.release}
              </Link>
            </span>
            {run.build ? <span className="mono">{run.build}</span> : null}
            {run.environment ? <span>{run.environment}</span> : null}
            <span>
              {counts.passed} passed, {counts.failed} failed, {counts.blocked} blocked, {counts.not_run} not run
            </span>
          </p>
        </div>
        <div className="run-head-actions">
          <SaveBadge waiting={outbox.waiting} saving={unsaved} onRetry={outbox.retry} />
          {done ? (
            <span className="chip chip-ver">Complete</span>
          ) : editable ? (
            <Button variant="primary" disabled={complete.isPending || unsaved} onClick={finish}>
              {complete.isPending ? 'Checking…' : 'Complete run'}
            </Button>
          ) : null}
        </div>
      </header>
      <ProjectNav projectKey={projectKey} />

      <p className="sr-only" role="status" aria-live="polite">
        {announce}
      </p>
      {outbox.refusal ? (
        <p className="field-error run-banner" role="alert">
          {outbox.refusal}
        </p>
      ) : null}
      {problem ? (
        <p className="field-error run-banner" role="alert">
          {problem}
        </p>
      ) : null}
      {missing.length ? (
        <div className="run-missing" role="alert">
          <p>
            <strong>{serverMessage(complete.error)}</strong>
          </p>
          <ul>
            {missing.map((m) => (
              <li key={m.result_id}>
                <button
                  type="button"
                  className="link-button"
                  onClick={() => setCursor(cases.findIndex((c) => c.result_id === m.result_id))}
                >
                  {m.case}
                </button>{' '}
                {m.title}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {!cases.length ? (
        <p className="faint">
          No cases in this plan version yet. <Link to={`${base}/runs`}>Back to runs</Link>
        </p>
      ) : (
        <div className="run-layout">
          <ol className="run-cases" aria-label="Cases">
            {cases.map((c, i) => (
              <li
                key={c.result_id}
                ref={(el) => {
                  rowRefs.current[i] = el
                }}
              >
                <button
                  type="button"
                  className="run-case"
                  aria-current={i === cursor ? 'true' : undefined}
                  onClick={() => setCursor(i)}
                >
                  <Mark kind={BY_ID[c.outcome].mark} />
                  <span className="run-case-id mono">{c.case}</span>
                  <span className="run-case-title">{c.title}</span>
                  <SaveDot state={outbox.states[c.result_id]} />
                </button>
              </li>
            ))}
          </ol>

          {current ? (
            <section
              className="run-current"
              aria-label={`${current.case}: ${current.title}`}
              onDragOver={(e) => editable && e.preventDefault()}
              onDrop={(e) => {
                if (!editable) return
                e.preventDefault()
                void attach(current, Array.from(e.dataTransfer.files))
              }}
            >
              <div className="run-current-head">
                <IdTag id={current.case} to={`${base}/cases/${Number(current.case.split('-')[1])}`} />
                <StatusChip status={BY_ID[current.outcome].status} />
                <span className="faint small">
                  {cursor + 1} of {cases.length}
                </span>
              </div>
              <h2 className="run-current-title">{current.title}</h2>
              {current.preconditions ? (
                <p className="muted">
                  <span className="overline">Before you start</span> {current.preconditions}
                </p>
              ) : null}
              <ol className="run-steps">
                {current.steps.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ol>
              <p className="run-expected">
                <span className="overline">Expected</span>
                {current.expected}
              </p>

              <div className="run-outcomes" role="group" aria-label="Record the result">
                {OUTCOMES.map((o) => (
                  <button
                    key={o.id}
                    type="button"
                    className="outcome-key"
                    data-on={current.outcome === o.id || undefined}
                    disabled={!editable}
                    onClick={() => setOutcome(o.id)}
                  >
                    <Mark kind={o.mark} coloured={current.outcome !== o.id} />
                    {o.word}
                    <kbd>{o.key}</kbd>
                  </button>
                ))}
              </div>

              <label className="field">
                <span className="field-label">Note</span>
                <textarea
                  key={current.result_id}
                  className="textarea"
                  defaultValue={current.note}
                  disabled={!editable}
                  placeholder="What happened, if it didn't pass"
                  onBlur={(e) => e.target.value !== current.note && setOutcome(current.outcome, e.target.value)}
                />
              </label>

              <div className="run-evidence">
                <div className="run-evidence-head">
                  <h3 className="overline">Evidence</h3>
                  {editable ? (
                    <Button size="sm" onClick={() => fileInput.current?.click()}>
                      Attach evidence <kbd>E</kbd>
                    </Button>
                  ) : null}
                </div>
                <EvidenceList
                  files={current.evidence}
                  empty={
                    current.outcome === 'failed'
                      ? 'A failed case needs evidence before the run can be completed.'
                      : 'None attached.'
                  }
                />
                {uploading[current.result_id] ? <p className="faint small">Uploading…</p> : null}
                {editable ? (
                  <p className="faint small">
                    Paste a screenshot, drop files here, or press <kbd>E</kbd>. Use test data only: no real customer
                    details.
                  </p>
                ) : null}
                <input
                  ref={fileInput}
                  type="file"
                  multiple
                  hidden
                  accept="image/*,video/*,.pdf,.txt,.log,.har"
                  onChange={(e) => {
                    void attach(current, Array.from(e.target.files ?? []))
                    e.target.value = ''
                  }}
                />
              </div>

              {current.outcome === 'failed' ? (
                <div className="run-defects">
                  <h3 className="overline">Defects</h3>
                  {current.defects.map((d) => (
                    <p key={d.display_id}>
                      <IdTag id={d.display_id} to={`${base}/bugs/${d.number}`} />{' '}
                      <StatusChip status={d.chip} word={d.shown_as} />
                    </p>
                  ))}
                  {!current.defects.length && CAN_TEST.includes(membership.role) ? (
                    <Button onClick={() => fileDefect(current)}>Create defect</Button>
                  ) : null}
                </div>
              ) : null}
            </section>
          ) : null}
        </div>
      )}
    </div>
  )
}

function SaveDot({ state }: { state?: SaveState }) {
  if (!state || state === 'saved') return null
  const word = { saving: 'Saving…', waiting: 'Not sent yet', refused: 'Not saved' }[state]
  return <span className={`save-dot save-${state}`}>{word}</span>
}

function SaveBadge({ waiting, saving, onRetry }: { waiting: number; saving: boolean; onRetry: () => void }) {
  if (waiting) {
    return (
      <span className="save-badge" role="status">
        {waiting} {waiting === 1 ? 'result' : 'results'} not sent yet.{' '}
        <button type="button" className="link-button" onClick={onRetry}>
          Retry
        </button>
      </span>
    )
  }
  return (
    <span className="save-badge faint" role="status">
      {saving ? 'Saving…' : 'Saved'}
    </span>
  )
}
