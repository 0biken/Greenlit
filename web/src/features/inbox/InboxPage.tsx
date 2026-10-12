import { useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import type { InboxGroup, InboxItem, NextAction } from '../../api/records'
import { useInbox, useUnsnooze } from '../../api/queries'
import { useHotkeys } from '../../app/hotkeys'
import { Button } from '../../design/Button'
import { IdTag } from '../../design/IdTag'
import { Mark } from '../../design/Mark'
import { Menu, MenuItem } from '../../design/overlays'
import { EmptyState, ErrorState, SkeletonRows } from '../../design/states'
import { STATUS, StatusChip } from '../../design/StatusChip'
import { RetestDialog } from '../defects/RetestDialog'
import { SnoozeDialog } from './SnoozeDialog'
import './inbox.css'

// The QA Inbox (UX wireframe, FR-INB-01): one list across the user's projects, grouped by
// urgency, open work first, each row with its age and one next action.

const GROUPS: { id: InboxGroup; label: string }[] = [
  { id: 'closed_failed_retest', label: 'Closed with a failed retest' },
  { id: 'needs_retest', label: 'Fixed but not retested' },
  { id: 'aging_defects', label: 'Ageing defects' },
  { id: 'unfiled_failures', label: 'Failures without a defect' },
  { id: 'missing_evidence', label: 'Missing evidence' },
  { id: 'stale_tests', label: 'Stale tests' },
  { id: 'uncovered', label: 'Requirements without tests' },
]

const ACTION_LABEL: Record<NextAction, string> = {
  retest: 'Retest',
  run: 'Run',
  add_case: 'Add case',
  open: 'Open',
  file_defect: 'File defect',
  attach_evidence: 'Attach evidence',
}

function age(days: number) {
  if (days === 0) return 'today'
  return days === 1 ? '1 day' : `${days} days`
}

function recordPath(item: Pick<InboxItem, 'project_key' | 'display_id'>) {
  const [prefix, no] = item.display_id.split('-')
  const kind = { BUG: 'bugs', TC: 'cases', REQ: 'requirements' }[prefix] ?? 'records'
  return `/${item.project_key.toLowerCase()}/${kind}/${no}`
}

export function InboxPage() {
  const [params, setParams] = useSearchParams()
  const filter = (params.get('group') as InboxGroup | 'snoozed' | null) ?? null
  const showSnoozed = filter === 'snoozed'
  const inbox = useInbox(showSnoozed)
  const counts = useInbox(false).data
  const navigate = useNavigate()

  const [rawCursor, setCursor] = useState(0)
  const [snoozing, setSnoozing] = useState<InboxItem | null>(null)
  const [retesting, setRetesting] = useState<InboxItem | null>(null)
  const rowRefs = useRef<(HTMLLIElement | null)[]>([])

  const items = useMemo(() => {
    const all = inbox.data?.items ?? []
    return showSnoozed || !filter ? all : all.filter((i) => i.group === filter)
  }, [inbox.data, filter, showSnoozed])

  // Critical items sit on top in their own band; the rest follow in group order.
  const critical = showSnoozed ? [] : items.filter((i) => i.critical)
  const sections = GROUPS.map((g) => ({
    ...g,
    items: items.filter((i) => i.group === g.id && (showSnoozed || !i.critical)),
  })).filter((s) => s.items.length)
  const ordered = [...critical, ...sections.flatMap((s) => s.items)]

  // Keep the cursor on a real row when items leave the list.
  const cursor = Math.min(rawCursor, Math.max(ordered.length - 1, 0))

  function act(item: InboxItem) {
    if (item.next_action === 'retest') setRetesting(item)
    else navigate(recordPath(item))
  }

  // No animation on keyboard moves: the focus just jumps.
  function move(delta: number) {
    if (!ordered.length) return
    const next = Math.min(Math.max(cursor + delta, 0), ordered.length - 1)
    setCursor(next)
    rowRefs.current[next]?.focus()
  }
  useHotkeys({
    j: () => move(1),
    k: () => move(-1),
    ArrowDown: () => move(1),
    ArrowUp: () => move(-1),
    Enter: () => ordered[cursor] && navigate(recordPath(ordered[cursor])),
    a: () => ordered[cursor] && act(ordered[cursor]),
    s: () => ordered[cursor] && !showSnoozed && setSnoozing(ordered[cursor]),
  })

  const total = counts ? Object.values(counts.counts).reduce((a, b) => a + b, 0) : null
  let index = 0
  const row = (item: InboxItem) => {
    const i = index++
    return (
      <InboxRow
        key={`${item.group}:${item.id}`}
        item={item}
        current={i === cursor}
        snoozedView={showSnoozed}
        rowRef={(el) => {
          rowRefs.current[i] = el
        }}
        onFocus={() => setCursor(i)}
        onAct={() => act(item)}
        onSnooze={() => setSnoozing(item)}
      />
    )
  }

  return (
    <div className="inbox">
      <header className="page-head">
        <div>
          <h1 className="page-title">Inbox</h1>
          <p className="page-sub">
            {total === null
              ? 'Checking what needs you…'
              : total === 0
                ? 'Nothing open across your projects.'
                : `${total} ${total === 1 ? 'item needs' : 'items need'} you across your projects.`}
          </p>
        </div>
      </header>

      <div className="inbox-layout">
        <nav className="inbox-filters" aria-label="Inbox groups">
          <FilterLink label="Everything" count={total} active={!filter} onClick={() => setParams({})} />
          {GROUPS.map((g) => (
            <FilterLink
              key={g.id}
              label={g.label}
              count={counts?.counts[g.id] ?? null}
              active={filter === g.id}
              onClick={() => setParams({ group: g.id })}
            />
          ))}
          <div className="inbox-filters-sep" />
          <FilterLink
            label="Snoozed"
            count={counts?.snoozed ?? null}
            active={showSnoozed}
            onClick={() => setParams({ group: 'snoozed' })}
          />
        </nav>

        <section className="inbox-main" aria-live="polite">
          {inbox.isPending ? (
            <SkeletonRows rows={7} />
          ) : inbox.isError && !inbox.data ? (
            <ErrorState message="Couldn't load your Inbox." onRetry={() => inbox.refetch()} />
          ) : !ordered.length ? (
            <EmptyState title={showSnoozed ? 'Nothing is snoozed.' : 'Nothing needs you right now.'}>
              {!showSnoozed && inbox.data?.next_release ? (
                <>
                  Next release: {inbox.data.next_release.project_key} {inbox.data.next_release.version}, due{' '}
                  {new Date(inbox.data.next_release.due).toLocaleDateString('en-GB', { day: 'numeric', month: 'long' })}.
                </>
              ) : null}
            </EmptyState>
          ) : (
            <>
              {inbox.isError ? (
                <p className="stale-copy" role="status">
                  Couldn't refresh. Showing the last loaded copy.{' '}
                  <button type="button" className="link-button" onClick={() => inbox.refetch()}>
                    Retry
                  </button>
                </p>
              ) : null}
              {critical.length ? (
                <div className="critical-band" role="group" aria-label="Critical">
                  <div className="ledger-group">
                    <h2 className="overline">Critical · {critical.length}</h2>
                    <span className="faint small">Closed in the tracker, but the retest failed</span>
                  </div>
                  <ul className="inbox-list">{critical.map(row)}</ul>
                </div>
              ) : null}
              {sections.map((s) => (
                <div key={s.id} role="group" aria-label={s.label}>
                  <div className="ledger-group">
                    <h2 className="overline">
                      {s.label} · {s.items.length}
                    </h2>
                  </div>
                  <ul className="inbox-list">{s.items.map(row)}</ul>
                </div>
              ))}
              <p className="inbox-keys faint">
                <kbd>j</kbd> <kbd>k</kbd> to move, <kbd>a</kbd> for the next action, <kbd>s</kbd> to snooze, <kbd>?</kbd> for all
                shortcuts
              </p>
            </>
          )}
        </section>
      </div>

      <SnoozeDialog item={snoozing} onClose={() => setSnoozing(null)} />
      <RetestDialog
        defect={
          retesting
            ? { projectKey: retesting.project_key, displayId: retesting.display_id, title: retesting.title }
            : null
        }
        onClose={() => setRetesting(null)}
      />
    </div>
  )
}

function FilterLink({ label, count, active, onClick }: { label: string; count: number | null; active: boolean; onClick: () => void }) {
  return (
    <button type="button" className="filter" aria-current={active ? 'true' : undefined} onClick={onClick}>
      <span>{label}</span>
      <span className="filter-count">{count ?? '–'}</span>
    </button>
  )
}

function InboxRow({
  item,
  current,
  snoozedView,
  rowRef,
  onFocus,
  onAct,
  onSnooze,
}: {
  item: InboxItem
  current: boolean
  snoozedView: boolean
  rowRef: (el: HTMLLIElement | null) => void
  onFocus: () => void
  onAct: () => void
  onSnooze: () => void
}) {
  const unsnooze = useUnsnooze()
  const def = STATUS[item.status]
  const spokenAge = item.age_days === 0 ? 'today' : `${age(item.age_days)}`
  return (
    <li
      ref={rowRef}
      tabIndex={current ? 0 : -1}
      onFocus={onFocus}
      className="ledger-row inbox-row"
      data-current={current || undefined}
      aria-label={`${item.display_id}, ${item.title}, ${def.word}, ${spokenAge}`}
    >
      <span className="ledger-margin">
        <span className="inbox-age">{item.age_days === 0 ? 'new' : `${item.age_days}d`}</span>
        <Mark kind={def.mark} />
      </span>
      <span className="ledger-body inbox-body">
        <span className="inbox-main-line">
          <IdTag id={item.display_id} to={recordPath(item)} />
          <span className="inbox-title">{item.title}</span>
        </span>
        <span className="inbox-meta">
          <span>{item.project_name}</span>
          {item.owner_name ? <span>{item.owner_name}</span> : null}
          {item.escalated ? <span className="inbox-escalated">Overdue for a retest</span> : null}
          {snoozedView && item.snooze_reason ? <span>Snoozed: {item.snooze_reason}</span> : null}
        </span>
        <span className="inbox-status">
          <StatusChip status={item.status} detail={age(item.age_days)} srDetail={spokenAge} />
        </span>
        <span className="inbox-actions">
          {snoozedView ? (
            <Button size="sm" disabled={unsnooze.isPending} onClick={() => unsnooze.mutate(item.id)}>
              Unsnooze
            </Button>
          ) : (
            <>
              <Button size="sm" variant={item.next_action === 'retest' ? 'primary' : 'secondary'} onClick={onAct}>
                {ACTION_LABEL[item.next_action]}
              </Button>
              <Menu
                trigger={
                  <button type="button" className="row-menu" aria-label={`More for ${item.display_id}`}>
                    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
                      <circle cx="3.5" cy="8" r="1.3" fill="currentColor" />
                      <circle cx="8" cy="8" r="1.3" fill="currentColor" />
                      <circle cx="12.5" cy="8" r="1.3" fill="currentColor" />
                    </svg>
                  </button>
                }
              >
                <MenuItem onSelect={onSnooze}>Snooze…</MenuItem>
              </Menu>
            </>
          )}
        </span>
      </span>
    </li>
  )
}
