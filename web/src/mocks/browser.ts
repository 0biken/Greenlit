import { setupWorker } from 'msw/browser'
import { backendHandlers, plannedHandlers } from './handlers'

// VITE_MOCKS=planned (default in development): mock only endpoints not built yet; everything
//   else goes through the Vite proxy to Django.
// VITE_MOCKS=all: also stand in for sign-in and the existing API, to preview with no backend.
// VITE_MOCKS=off: no mocks at all.
export async function startMocks() {
  const mode = (import.meta.env.VITE_MOCKS as string | undefined) ?? 'planned'
  if (mode === 'off') return
  const handlers = mode === 'all' ? [...plannedHandlers, ...backendHandlers] : plannedHandlers
  await setupWorker(...handlers).start({ onUnhandledFrame: 'bypass', quiet: true })
}
