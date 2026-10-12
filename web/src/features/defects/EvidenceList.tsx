import { useState } from 'react'
import { fileDownloadUrl } from '../../api/queries'
import type { EvidenceFile } from '../../api/records'
import { IdTag } from '../../design/IdTag'

// Evidence files with their EV numbers. Opening one asks the file service for a short-lived
// link; a file that is still being scanned is not served yet.
export function EvidenceList({ files, empty = 'No evidence attached.' }: { files: EvidenceFile[]; empty?: string }) {
  const [problem, setProblem] = useState<string | null>(null)
  if (!files.length) return <p className="faint small">{empty}</p>

  async function open(file: EvidenceFile) {
    setProblem(null)
    // Open the tab first, inside the click, so the browser does not block it as a pop-up.
    const tab = window.open('', '_blank')
    try {
      const url = await fileDownloadUrl(file.file_id)
      ;(tab ?? window).location.assign(url)
    } catch {
      tab?.close()
      setProblem(
        file.state === 'available'
          ? `Couldn't open ${file.display_id}. Try again.`
          : `${file.display_id} is still being checked. Try again in a moment.`,
      )
    }
  }

  return (
    <div>
      <ul className="evidence-list">
        {files.map((f) => (
          <li key={f.display_id}>
            <IdTag id={f.display_id} />
            <button type="button" className="link-button evidence-name" onClick={() => open(f)}>
              {f.name}
            </button>
          </li>
        ))}
      </ul>
      {problem ? (
        <p className="field-error" role="alert">
          {problem}
        </p>
      ) : null}
    </div>
  )
}
