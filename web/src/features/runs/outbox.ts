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

export function useOutbox(project: string, run: number, onSaved: (resultId: string, saved: Pending) => void) {
  const key = storageKey(project, run)
  // What was still unsent when the page opened (after a reload, or coming back online).
  const [unsent] = useState<Queue>(() => read(key))
  const queue = useRef<Queue>(unsent)
  const sending = useRef(false)
  const [states, setStates] = useState<Record<string, SaveState>>(() =>
    Object.fromEntries(Object.keys(unsent).map((id) => [id, 'waiting' as SaveState])),
  )
  const [refusal, setRefusal] = useState<string | null>(null)
  const savedRef = useRef(onSaved)
  useEffect(() => {
    savedRef.current = onSaved
  })

  const mark = (id: string, state: SaveState) => setStates((s) => ({ ...s, [id]: state }))

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
          if (error instanceof ApiError && error.status < 500) {
            // The server understood and said no (the run was completed, or access changed).
            // Retrying will not help, so drop it and say why.
            delete queue.current[id]
            write(key, queue.current)
            mark(id, 'refused')
            setRefusal(serverMessage(error) ?? "The server didn't accept this result.")
            continue
          }
          // No connection, or the server is down: keep everything and try again later.
          for (const waiting of Object.keys(queue.current)) mark(waiting, 'waiting')
          break
        }
        // Only clear it if nothing newer was recorded for this case while it was in flight.
        if (queue.current[id] === item) {
          delete queue.current[id]
          write(key, queue.current)
          mark(id, 'saved')
          savedRef.current(id, item)
        }
      }
    } finally {
      sending.current = false
    }
  }, [key, project, run])

  const record = useCallback(
    (resultId: string, value: Pending) => {
      queue.current = { ...queue.current, [resultId]: value }
      write(key, queue.current)
      mark(resultId, 'saving')
      setRefusal(null)
      void flush()
    },
    [flush, key],
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
  return { record, states, unsent, waiting, refusal, retry: flush }
}
