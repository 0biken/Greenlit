import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getCurrentOrg } from '../../api/client'
import { saveResult, serverMessage } from '../../api/queries'
import type { Outcome } from '../../api/records'

// Results recorded in a run are kept in the browser first and sent in the order they were
// made (UX "Offline or slow connections"). A save that fails for lack of a connection stays
// queued and is retried; the queue survives a reload. Only the latest value per case is kept,
// because the server keeps only the latest too.

export type Pending = { outcome: Outcome; note: string }
export type SaveState = 'saved' | 'saving' | 'waiting' | 'refused'

type Queue = Record<string, Pending>

const storageKey = (project: string, run: number) => `greenlit.outbox.${getCurrentOrg()}.${project}.${run}`

function read(key: string): Queue {
  try {
    return JSON.parse(localStorage.getItem(key) ?? '{}') as Queue
  } catch {
    return {}
  }
}

function write(key: string, queue: Queue) {
  try {
    if (Object.keys(queue).length) localStorage.setItem(key, JSON.stringify(queue))
    else localStorage.removeItem(key)
  } catch {
    // Storage is full or blocked: the queue still lives in memory for this visit.
  }
}

// Answers that mean "not this result, ever": the run is complete, the result is gone, the value
// is invalid. Anything else below 500 (signed out, a permission check, a rate limit, a timeout)
// says nothing about the result itself, so the result stays queued.
const REFUSALS = new Set([400, 404, 409, 410, 422])

export function useOutbox(project: string, run: number, onSaved: (resultId: string, saved: Pending) => void) {
  const key = storageKey(project, run)
  // `pending` is what is recorded here and not yet on the server; it starts as whatever was
  // still unsent when the page opened (after a reload, or coming back online).
  const [pending, setPending] = useState<Queue>(() => read(key))
  const queue = useRef<Queue>(pending)
  const sending = useRef(false)
  const [states, setStates] = useState<Record<string, SaveState>>(() =>
    Object.fromEntries(Object.keys(pending).map((id) => [id, 'waiting' as SaveState])),
  )
  const [refusal, setRefusal] = useState<string | null>(null)
  const savedRef = useRef(onSaved)
  useEffect(() => {
    savedRef.current = onSaved
  })

  const mark = (id: string, state: SaveState) => setStates((s) => ({ ...s, [id]: state }))

  const store = useCallback(
    (next: Queue) => {
      queue.current = next
      write(key, next)
      setPending(next)
    },
    [key],
  )
  const drop = useCallback(
    (id: string) => {
      const next = { ...queue.current }
      delete next[id]
      store(next)
    },
    [store],
  )

  const flush = useCallback(async () => {
    if (sending.current) return
    sending.current = true
    try {
      for (;;) {
        const id = Object.keys(queue.current)[0]
        if (!id) break
        const item = queue.current[id]
        mark(id, 'saving')
        try {
          await saveResult(project, run, id, item.outcome, item.note)
        } catch (error) {
          if (error instanceof ApiError && REFUSALS.has(error.status)) {
            // The server understood and said no to this result (the run was completed).
            // Retrying will not help, so drop it and say why.
            drop(id)
            mark(id, 'refused')
            setRefusal(serverMessage(error) ?? "The server didn't accept this result.")
            continue
          }
          // No connection, the server is down, or you need to sign in again: keep everything
          // and try again later.
          for (const waiting of Object.keys(queue.current)) mark(waiting, 'waiting')
          break
        }
        // Only clear it if nothing newer was recorded for this case while it was in flight.
        if (queue.current[id] === item) {
          savedRef.current(id, item)
          drop(id)
          mark(id, 'saved')
        }
      }
    } finally {
      sending.current = false
    }
  }, [drop, project, run])

  const record = useCallback(
    (resultId: string, value: Pending) => {
      store({ ...queue.current, [resultId]: value })
      mark(resultId, 'saving')
      setRefusal(null)
      void flush()
    },
    [flush, store],
  )

  // Retry when the connection returns, and every few seconds while something is waiting.
  useEffect(() => {
    void flush()
    const retry = () => void flush()
    window.addEventListener('online', retry)
    const timer = window.setInterval(() => {
      if (Object.keys(queue.current).length) retry()
    }, 8000)
    return () => {
      window.removeEventListener('online', retry)
      window.clearInterval(timer)
    }
  }, [flush])

  const waiting = Object.values(states).filter((s) => s === 'waiting').length
  return { record, states, pending, waiting, refusal, retry: flush }
}
