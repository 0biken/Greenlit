import { useState, type FormEvent } from 'react'
import { useRetest } from '../../api/queries'
import { Button } from '../../design/Button'
import { Mark } from '../../design/Mark'
import { Dialog, DialogClose } from '../../design/overlays'

// FR-DEF-03 / UX Flow 2: record a retest. Evidence is required for a pass and for a fail.
// A pass makes the defect Verified; a fail makes it Retest failed and sends it back.
// The file goes through apps/files once M5 lands; the mock records only its name.

export function RetestDialog({
  defect,
  onClose,
}: {
  defect: { displayId: string; title: string } | null
  onClose: () => void
}) {
  const retest = useRetest()
  const [outcome, setOutcome] = useState<'passed' | 'failed' | null>(null)
  const [files, setFiles] = useState<File[]>([])
  // Keep showing the last defect while the dialog fades out.
  const [shown, setShown] = useState(defect)
  if (defect && defect !== shown) setShown(defect)

  function reset() {
    setOutcome(null)
    setFiles([])
    retest.reset()
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!defect || !outcome || !files.length) return
    await retest.mutateAsync({ displayId: defect.displayId, outcome, evidence: files.map((f) => f.name) })
    reset()
    onClose()
  }

  const ready = outcome !== null && files.length > 0
  return (
    <Dialog
      open={defect !== null}
      onOpenChange={(open) => {
        if (!open) {
          reset()
          onClose()
        }
      }}
      title={shown ? `Retest ${shown.displayId}` : 'Retest'}
      description={shown?.title}
    >
      <form onSubmit={submit} className="dialog-form">
        <fieldset className="outcomes">
          <legend className="field-label">Result</legend>
          <label className="outcome" data-tone="pass">
            <input type="radio" name="outcome" checked={outcome === 'passed'} onChange={() => setOutcome('passed')} />
            <Mark kind="pass" size={18} />
            <span>
              <strong>Passed</strong>
              <span className="faint">The fix works. The defect becomes Verified.</span>
            </span>
          </label>
          <label className="outcome" data-tone="fail">
            <input type="radio" name="outcome" checked={outcome === 'failed'} onChange={() => setOutcome('failed')} />
            <Mark kind="fail" size={18} />
            <span>
              <strong>Failed</strong>
              <span className="faint">It still happens. The defect goes back to the developer.</span>
            </span>
          </label>
        </fieldset>

        <div className="field">
          <span className="field-label">Evidence</span>
          <label className="dropzone">
            <input
              type="file"
              accept="image/*,video/*,.pdf,.txt,.log,.har"
              capture="environment"
              multiple
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            />
            {files.length ? (
              <span>
                {files.length === 1 ? files[0].name : `${files.length} files`} attached. <u>Change</u>
              </span>
            ) : (
              <span>
                <u>Choose a screenshot, recording or log</u>, or take a photo. Required for a pass or a fail.
              </span>
            )}
          </label>
        </div>

        {retest.isError ? <p className="field-error">Couldn't save the retest. Try again.</p> : null}
        <div className="dialog-actions">
          <DialogClose asChild>
            <Button variant="quiet">Cancel</Button>
          </DialogClose>
          <Button type="submit" variant="primary" disabled={!ready || retest.isPending}>
            {retest.isPending ? 'Saving…' : 'Record retest'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
