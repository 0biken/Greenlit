import { useEffect, useLayoutEffect, useRef } from 'react'

// Keyboard first for daily work (UX rule 6). Shortcuts never animate: they are pressed
// hundreds of times a day and must feel instant.

export type Hotkeys = Record<string, (e: KeyboardEvent) => void>

function typingInto(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
}

/**
 * Keys are single characters ("j", "?", "Enter") or two-key sequences ("g i").
 * Ignored while typing, while a modifier is held, and while a dialog or menu is open.
 */
export function useHotkeys(map: Hotkeys, enabled = true) {
  const mapRef = useRef(map)
  useLayoutEffect(() => {
    mapRef.current = map
  })
  const prefix = useRef<{ key: string; at: number } | null>(null)

  useEffect(() => {
    if (!enabled) return
    function onKey(e: KeyboardEvent) {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || typingInto(e.target)) return
      if (document.querySelector('[role="dialog"], [role="menu"]')) return
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key
      const shown = e.key === '?' ? '?' : key
      const now = performance.now()
      if (prefix.current && now - prefix.current.at < 900) {
        const handler = mapRef.current[`${prefix.current.key} ${shown}`]
        prefix.current = null
        if (handler) {
          e.preventDefault()
          handler(e)
          return
        }
      }
      if (Object.keys(mapRef.current).some((k) => k.startsWith(`${shown} `))) {
        prefix.current = { key: shown, at: now }
        return
      }
      const handler = mapRef.current[shown]
      if (handler) {
        e.preventDefault()
        handler(e)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled])
}
