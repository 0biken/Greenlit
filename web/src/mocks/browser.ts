import { setupWorker } from 'msw/browser'
import { backendHandlers, sampleHandlers } from './handlers'

// Normal development talks to the real API through the Vite proxy: nothing is mocked.
// `pnpm dev:mock` (VITE_MOCKS=all) serves sample data for every endpoint, sign-in included, so
// the screens can be previewed with no backend running.
export async function startMocks() {
  if (import.meta.env.VITE_MOCKS !== 'all') return
  const handlers = [...sampleHandlers, ...backendHandlers]
  await setupWorker(...handlers).start({ onUnhandledFrame: 'bypass', quiet: true })
}
