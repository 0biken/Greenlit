import { useState, type FormEvent } from 'react'
import { serverMessage, useRetest } from '../../api/queries'
import { Button } from '../../design/Button'
import { Mark } from '../../design/Mark'
import { Dialog, DialogClose } from '../../design/overlays'

// FR-DEF-03 / UX Flow 2: record a retest. Evidence is required for a pass and for a fail.
// A pass makes the defect Verified; a fail makes it Retest failed and sends it back.
// Each file is uploaded through the file service first; the retest then names their IDs.

export function RetestDialog({
  defect,
  onClose,
}: {
  defect: { projectKey: string; displayId: string; title: string } | null
  onClose: () => void
}) {
  const retest = useRetest()
  const [outcome, setOutcome] = useState<'passed' | 'failed' | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [progress, setProgress] = useState<Record<number, 'uploading' | 'attached'>>({})
  // Keep showing the last defect while the dialog fades out.
  const [shown, setShown] = useState(defect)
  if (defect && defect !== shown) setShown(defect)

  function reset() {
    setOutcome(null)
    setFiles([])
    setProgress({})
    retest.reset()
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!defect || !outcome || !files.length) return
    setProgress({})
    try {
      await retest.mutateAsync({
        projectKey: defect.projectKey,
        displayId: defect.displayId,
        outcome,
        files,
        onProgress: (index, state) => setProgress((p) => ({ ...p, [index]: state })),
      })
    } catch {
      return // the message is shown from retest.error
    }
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
              disabled={retest.isPending}
              onChange={(e) => {
                setFiles(Array.from(e.target.files ?? []))
                setProgress({})
              }}
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

        {retest.isPending || Object.keys(progress).length ? (
          <ul className="upload-list" aria-live="polite">
            {files.map((f, i) => (
              <li key={f.name + i}>
                <span className="upload-name">{f.name}</span>
                <span className="faint">
                  {progress[i] === 'attached' ? 'Attached' : progress[i] === 'uploading' ? 'Uploading…' : 'Waiting'}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        {retest.isError ? (
          <p className="field-error" role="alert">
            {serverMessage(retest.error) ?? "Couldn't save the retest. Try again."}
          </p>
        ) : null}
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
