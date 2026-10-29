import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, getCurrentOrg } from '../../api/client'
import { Button } from '../../design/Button'
import { EmptyState, ErrorState, SkeletonRows } from '../../design/states'
import './requirements.css'

type Source = {
  id: string
  kind: string
  title: string
  content_text: string
  page_count: number | null
  extraction_index: { page: number | null; start_char: number; end_char: number }[]
  stored_file_id: string | null
  created_at: string
}

type UploadStarted = {
  file: { id: string }
  upload: {
    method: 'PUT' | 'POST'
    url: string
    fields: Record<string, string>
    headers: Record<string, string>
  }
}

type Requirement = {
  id: string
  display_no: number
  title: string
  text: string
  priority: 'critical' | 'high' | 'medium' | 'low'
  revision: number
  source_document_id: string | null
  source_locator: { quote?: string; start_line?: number; page?: number }
  review_state: 'draft' | 'accepted' | 'rejected'
  origin: 'human' | 'ai'
  created_at: string
}

const PRIORITIES = ['critical', 'high', 'medium', 'low'] as const
const word = (value: string) => value.charAt(0).toUpperCase() + value.slice(1)

export function RequirementsPage() {
  const { projectKey = '' } = useParams()
  const key = projectKey.toUpperCase()
  const orgKey = getCurrentOrg() ?? '-'
  const client = useQueryClient()
  const [pendingSourceFile, setPendingSourceFile] = useState<string | null>(null)
  useEffect(() => {
    if (!pendingSourceFile) return
    const timeout = window.setTimeout(() => setPendingSourceFile(null), 2 * 60 * 1000)
    return () => window.clearTimeout(timeout)
  }, [pendingSourceFile])
  const sources = useQuery({
    queryKey: ['org', orgKey, 'project', key, 'sources'],
    queryFn: () => api<Source[]>(`/api/projects/${encodeURIComponent(key)}/sources/`),
    refetchInterval: (query) => {
      if (!pendingSourceFile || query.state.data?.some((source) => source.stored_file_id === pendingSourceFile)) return false
      return 2000
    },
  })
  const requirements = useQuery({
    queryKey: ['org', orgKey, 'project', key, 'requirements'],
    queryFn: () => api<Requirement[]>(`/api/projects/${encodeURIComponent(key)}/requirements/`),
  })
  const [sourceTitle, setSourceTitle] = useState('')
  const [sourceText, setSourceText] = useState('')
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [priority, setPriority] = useState<(typeof PRIORITIES)[number]>('medium')
  const [sourceId, setSourceId] = useState('')
  const [quote, setQuote] = useState('')
  const [saveAsDraft, setSaveAsDraft] = useState(false)
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [message, setMessage] = useState('')

  const refresh = () => {
    void client.invalidateQueries({ queryKey: ['org', orgKey, 'project', key] })
  }
  const addSource = useMutation({
    mutationFn: () =>
      api<Source>(`/api/projects/${encodeURIComponent(key)}/sources/`, {
        method: 'POST',
        body: { title: sourceTitle, kind: 'prd', content_text: sourceText },
      }),
    onSuccess: () => {
      setSourceTitle('')
      setSourceText('')
      setMessage('Source saved.')
      refresh()
    },
    onError: () => setMessage('Could not save the source. Check that it has a title and text, then try again.'),
  })
  const uploadSource = useMutation({
    mutationFn: async (file: File) => {
      const started = await api<UploadStarted>(`/api/projects/${encodeURIComponent(key)}/files/`, {
        method: 'POST',
        body: { kind: 'prd', name: file.name, size: file.size },
      })
      let response: Response
      if (started.upload.method === 'PUT') {
        response = await fetch(started.upload.url, {
          method: 'PUT',
          headers: started.upload.headers,
          body: file,
        })
      } else {
        const form = new FormData()
        for (const [name, value] of Object.entries(started.upload.fields)) form.append(name, value)
        form.append('file', file)
        response = await fetch(started.upload.url, { method: 'POST', body: form })
      }
      if (!response.ok) throw new Error('Upload failed')
      return api<{ id: string; state: string }>(`/api/files/${started.file.id}/complete/`, {
        method: 'POST',
      })
    },
    onSuccess: (file) => {
      setPendingSourceFile(file.id)
      setMessage(file.state === 'available'
        ? 'PRD uploaded and processed. It is now in Sources.'
        : 'PRD uploaded. Malware scanning and text extraction are running in the background.')
      refresh()
    },
    onError: () => setMessage('Could not upload this PRD. Check the file type and 20 MB limit, then try again.'),
  })
  const addRequirement = useMutation({
    mutationFn: () =>
      api<Requirement>(`/api/projects/${encodeURIComponent(key)}/requirements/`, {
        method: 'POST',
        body: {
          title,
          text,
          priority,
          review_state: saveAsDraft ? 'draft' : 'accepted',
          ...(sourceId ? { source_document_id: sourceId, source_locator: { quote } } : {}),
        },
      }),
    onSuccess: () => {
      setTitle('')
      setText('')
      setQuote('')
      setSourceId('')
      setSaveAsDraft(false)
      setMessage('Requirement saved.')
      refresh()
    },
    onError: () => setMessage('Could not save the requirement. If a source is selected, check that the quote appears exactly in it.'),
  })
  const editRequirement = useMutation({
    mutationFn: (item: Requirement) =>
      api<Requirement>(`/api/requirements/${item.id}/`, {
        method: 'PATCH',
        body: { title: item.title, text: item.text, priority: item.priority },
      }),
    onSuccess: () => {
      setEditing(null)
      setMessage('Requirement updated.')
      refresh()
    },
    onError: () => setMessage('Could not update the requirement.'),
  })
  const review = useMutation({
    mutationFn: ({ id, review_state }: { id: string; review_state: 'accepted' | 'rejected' }) =>
      api<Requirement>(`/api/requirements/${id}/review/`, { method: 'POST', body: { review_state } }),
    onSuccess: () => {
      setMessage('Review decision saved.')
      refresh()
    },
    onError: () => setMessage('Could not save the review decision.'),
  })

  const shown = useMemo(() => {
    const rows = requirements.data ?? []
    return rows.filter((item) => {
      const stateMatches = filter === 'all' || item.review_state === filter
      const needle = search.trim().toLowerCase()
      const textMatches = !needle || `${item.title} ${item.text}`.toLowerCase().includes(needle)
      return stateMatches && textMatches
    })
  }, [requirements.data, filter, search])

  function saveEdit(item: Requirement) {
    editRequirement.mutate(item)
  }

  return (
    <div className="requirements-page">
      <header className="page-head">
        <div>
          <p className="crumbs"><Link to={`/${key.toLowerCase()}`}>{key}</Link><span aria-hidden="true">/</span>Requirements</p>
          <h1 className="page-title">Requirements</h1>
          <p className="page-sub">Keep each requirement connected to the source passage it came from.</p>
        </div>
        <Link className="btn btn-secondary btn-sm" to={`/${key.toLowerCase()}`}>Project home</Link>
      </header>

      <section className="requirements-section" aria-labelledby="source-h">
        <h2 id="source-h" className="overline dash-h">Sources</h2>
        <label className="requirements-upload">Upload a PRD<input type="file" accept=".pdf,.docx,.md,.markdown,.txt,.log" disabled={uploadSource.isPending} onChange={(event) => { const file = event.currentTarget.files?.[0]; if (file) uploadSource.mutate(file); event.currentTarget.value = '' }} /><span className="faint">PDF, DOCX, Markdown or plain text, up to 20 MB. Files are scanned before extraction.</span></label>
        <form className="requirements-form" onSubmit={(event) => { event.preventDefault(); addSource.mutate() }}>
          <label>Source title<input value={sourceTitle} maxLength={200} onChange={(event) => setSourceTitle(event.target.value)} required /></label>
          <label>Paste PRD or Markdown text<textarea value={sourceText} maxLength={1_000_000} rows={5} onChange={(event) => setSourceText(event.target.value)} required /></label>
          <div className="requirements-form-foot"><span className="faint">Plain text and Markdown, up to 1 MB.</span><Button variant="primary" type="submit" disabled={addSource.isPending}>Save source</Button></div>
        </form>
        {sources.isPending ? <SkeletonRows rows={2} /> : sources.isError ? <ErrorState message="Couldn't load sources." onRetry={() => sources.refetch()} /> : sources.data.length ? (
          <ul className="source-list">
            {sources.data.map((source) => <li key={source.id} className="source-item"><strong>{source.title}</strong><span className="faint">{source.stored_file_id ? 'Uploaded document' : 'Pasted text'}{source.page_count ? ` · ${source.page_count} pages` : ''}</span><details><summary>Read source text</summary><pre>{source.content_text}</pre></details></li>)}
          </ul>
        ) : <p className="faint">No source documents yet.</p>}
      </section>

      <section className="requirements-section" aria-labelledby="add-req-h">
        <h2 id="add-req-h" className="overline dash-h">Add a requirement</h2>
        <form className="requirements-form" onSubmit={(event) => { event.preventDefault(); addRequirement.mutate() }}>
          <label>Title<input value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} required /></label>
          <label>Requirement<textarea value={text} rows={3} onChange={(event) => setText(event.target.value)} required /></label>
          <div className="requirements-fields">
            <label>Priority<select value={priority} onChange={(event) => setPriority(event.target.value as (typeof PRIORITIES)[number])}>{PRIORITIES.map((value) => <option key={value} value={value}>{word(value)}</option>)}</select></label>
            <label>Source<select value={sourceId} onChange={(event) => { setSourceId(event.target.value); setQuote('') }}><option value="">No source selected</option>{(sources.data ?? []).map((source) => <option key={source.id} value={source.id}>{source.title}</option>)}</select></label>
          </div>
          {sourceId ? <label>Exact source quote<textarea value={quote} rows={2} onChange={(event) => setQuote(event.target.value)} required /><span className="faint">The quote must match the saved source exactly.</span></label> : null}
          <label className="requirements-check"><input type="checkbox" checked={saveAsDraft} onChange={(event) => setSaveAsDraft(event.target.checked)} /> Save for review as a draft</label>
          <div className="requirements-form-foot"><span className="faint">New requirements are human-authored.</span><Button variant="primary" type="submit" disabled={addRequirement.isPending}>Add requirement</Button></div>
        </form>
      </section>

      <section className="requirements-section" aria-labelledby="list-h">
        <h2 id="list-h" className="overline dash-h">Requirement list</h2>
        <div className="requirements-filters">
          <label>Search<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Title or text" /></label>
          <label>Review state<select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All states</option><option value="draft">Draft</option><option value="accepted">Accepted</option><option value="rejected">Rejected</option></select></label>
        </div>
        {requirements.isPending ? <SkeletonRows /> : requirements.isError ? <ErrorState message="Couldn't load requirements." onRetry={() => requirements.refetch()} /> : shown.length ? (
          <ul className="requirement-list">
            {shown.map((item) => <li className="requirement-card" key={item.id}>
              {editing === item.id ? <RequirementEditor item={item} onCancel={() => setEditing(null)} onSave={saveEdit} saving={editRequirement.isPending} /> : <>
                <div className="requirement-card-head"><span className="mono">REQ-{item.display_no}</span><span className={`requirement-state state-${item.review_state}`}>{word(item.review_state)}</span><span className="faint">{word(item.priority)} priority · revision {item.revision}</span></div>
                <h3>{item.title}</h3><p>{item.text}</p>
                {item.source_document_id ? <blockquote className="requirement-quote">“{item.source_locator.quote}” <span className="faint">· {sources.data?.find((source) => source.id === item.source_document_id)?.title ?? 'Source'}{item.source_locator.page ? ` · page ${item.source_locator.page}` : item.source_locator.start_line ? ` · line ${item.source_locator.start_line}` : ''}</span></blockquote> : <p className="faint">No source passage linked.</p>}
                <div className="requirement-actions"><Button size="sm" onClick={() => setEditing(item.id)}>Edit</Button>{item.review_state === 'draft' ? <><Button size="sm" variant="primary" disabled={review.isPending} onClick={() => review.mutate({ id: item.id, review_state: 'accepted' })}>Accept</Button><Button size="sm" variant="danger" disabled={review.isPending} onClick={() => review.mutate({ id: item.id, review_state: 'rejected' })}>Reject</Button></> : null}</div>
              </>}
            </li>)}
          </ul>
        ) : <EmptyState title="No requirements match this view.">Add one above or change the search and state filters.</EmptyState>}
      </section>
      {message ? <p className="requirements-message" role="status">{message}</p> : null}
    </div>
  )
}

function RequirementEditor({ item, onCancel, onSave, saving }: { item: Requirement; onCancel: () => void; onSave: (item: Requirement) => void; saving: boolean }) {
  const [draft, setDraft] = useState(item)
  return <form className="requirements-form editor-form" onSubmit={(event) => { event.preventDefault(); onSave(draft) }}>
    <label>Title<input value={draft.title} maxLength={200} onChange={(event) => setDraft({ ...draft, title: event.target.value })} required /></label>
    <label>Requirement<textarea value={draft.text} rows={3} onChange={(event) => setDraft({ ...draft, text: event.target.value })} required /></label>
    <label>Priority<select value={draft.priority} onChange={(event) => setDraft({ ...draft, priority: event.target.value as Requirement['priority'] })}>{PRIORITIES.map((value) => <option key={value} value={value}>{word(value)}</option>)}</select></label>
    <div className="requirement-actions"><Button type="submit" variant="primary" disabled={saving}>Save changes</Button><Button onClick={onCancel}>Cancel</Button></div>
  </form>
}
