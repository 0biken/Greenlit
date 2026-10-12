import { useState, type FormEvent } from 'react'
import type { InboxItem } from '../../api/records'
import { useSnooze } from '../../api/queries'
import { Button } from '../../design/Button'
import { Dialog, DialogClose } from '../../design/overlays'

// FR-INB-04: snooze with a reason and an end date. A snoozed item still counts towards readiness.
const PRESETS = [
  { label: '1 day', days: 1 },
  { label: '3 days', days: 3 },
  { label: '1 week', days: 7 },
]

export function SnoozeDialog({ item, onClose }: { item: InboxItem | null; onClose: () => void }) {
  const snooze = useSnooze()
  const [days, setDays] = useState(3)
  const [reason, setReason] = useState('')
  const [shown, setShown] = useState(item)
  if (item && item !== shown) setShown(item)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!item || !reason.trim()) return
    const until = new Date(Date.now() + days * 86_400_000).toISOString()
    await snooze.mutateAsync({ id: item.id, reason: reason.trim(), until })
    setReason('')
    onClose()
  }

  return (
    <Dialog
      open={item !== null}
      onOpenChange={(open) => !open && onClose()}
      title={shown ? `Snooze ${shown.display_id}` : 'Snooze'}
      description="It leaves your Inbox until then, and still counts towards release readiness."
    >
      <form onSubmit={submit} className="dialog-form">
        <fieldset className="segmented">
          <legend className="field-label">Until</legend>
          {PRESETS.map((p) => (
            <label key={p.days} className="segment">
              <input type="radio" name="days" checked={days === p.days} onChange={() => setDays(p.days)} />
              <span>{p.label}</span>
            </label>
          ))}
        </fieldset>
        <div className="field">
          <label className="field-label" htmlFor="snooze-reason">
            Reason
          </label>
          <textarea
            id="snooze-reason"
            className="textarea"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Waiting for the fix to reach staging"
            required
          />
        </div>
        {snooze.isError ? <p className="field-error">Couldn't snooze it. Try again.</p> : null}
        <div className="dialog-actions">
          <DialogClose asChild>
            <Button variant="quiet">Cancel</Button>
          </DialogClose>
          <Button type="submit" variant="primary" disabled={!reason.trim() || snooze.isPending}>
            {snooze.isPending ? 'Snoozing…' : `Snooze for ${PRESETS.find((p) => p.days === days)?.label}`}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
