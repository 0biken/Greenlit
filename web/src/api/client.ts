// One fetch wrapper for the app API and allauth's headless API.
// - Sends the CSRF token on every request (the cookie is set by GET /_allauth/browser/v1/config).
// - Names the organisation with the X-Org header (its slug).
// - Turns the server's answers into typed errors the screens can act on. Records the user
//   cannot see come back as 404 (never 403), so NotFound is a normal outcome, not a crash.

export const AUTH_BASE = '/_allauth/browser/v1'

let currentOrg: string | null = readStoredOrg()

function readStoredOrg(): string | null {
  try {
    return localStorage.getItem('greenlit.org')
  } catch {
    return null
  }
}

export function setCurrentOrg(slug: string | null) {
  currentOrg = slug
  try {
    if (slug) localStorage.setItem('greenlit.org', slug)
    else localStorage.removeItem('greenlit.org')
  } catch {
    // Storage can be blocked; the choice then lasts for this tab only.
  }
}

export function getCurrentOrg() {
  return currentOrg
}

export class ApiError extends Error {
  status: number
  code?: string
  body: unknown
  constructor(status: number, body: unknown, code?: string) {
    super(`Request failed with ${status}${code ? ` (${code})` : ''}`)
    this.status = status
    this.body = body
    this.code = code
  }
  get isNotFound() {
    return this.status === 404
  }
  get needsMfa() {
    return this.status === 403 && this.code === 'mfa_required'
  }
}

function csrfToken(): string | undefined {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : undefined
}

let csrfReady: Promise<unknown> | null = null
/** Make sure the CSRF cookie exists before the first unsafe request. */
export function ensureCsrf() {
  if (csrfToken()) return Promise.resolve()
  csrfReady ??= fetch(`${AUTH_BASE}/config`, { credentials: 'same-origin' })
  return csrfReady
}

type Options = {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  /** Send without the X-Org header (sign-in, /api/me/, creating an organisation). */
  noOrg?: boolean
  signal?: AbortSignal
}

async function send(url: string, { method = 'GET', body, noOrg, signal }: Options = {}) {
  if (method !== 'GET') await ensureCsrf()
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = csrfToken()
  if (token) headers['X-CSRFToken'] = token
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (!noOrg && currentOrg) headers['X-Org'] = currentOrg
  return fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
    signal,
  })
}

async function parse(response: Response): Promise<unknown> {
  if (response.status === 204) return null
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

/** App API call: resolves with the JSON body, or throws ApiError. */
export async function api<T>(path: string, options?: Options): Promise<T> {
  const response = await send(path, options)
  const body = await parse(response)
  if (!response.ok) {
    const code =
      body && typeof body === 'object' && 'code' in body ? String((body as { code: unknown }).code) : undefined
    throw new ApiError(response.status, body, code)
  }
  return body as T
}

// ---- allauth headless --------------------------------------------------------------------
// allauth answers 401 for "not finished yet" (verify email, second step), with the pending
// flow in data.flows. Those are steps, not failures, so they resolve rather than throw.

export type AuthFlow = { id: string; is_pending?: boolean }
export type AuthErrorItem = { message: string; code: string; param?: string }
export type AuthResult = {
  status: number
  authenticated: boolean
  pending: string | null
  flows: AuthFlow[]
  errors: AuthErrorItem[]
  data: unknown
  meta: Record<string, unknown>
}

export async function auth(path: string, options?: Omit<Options, 'noOrg'>): Promise<AuthResult> {
  const response = await send(AUTH_BASE + path, { ...options, noOrg: true })
  const body = ((await parse(response)) ?? {}) as {
    data?: { flows?: AuthFlow[] } & Record<string, unknown>
    meta?: Record<string, unknown>
    errors?: AuthErrorItem[]
  }
  const flows = body.data?.flows ?? []
  return {
    status: response.status,
    authenticated: Boolean(body.meta?.is_authenticated) && response.ok,
    pending: flows.find((f) => f.is_pending)?.id ?? null,
    flows,
    errors: body.errors ?? [],
    data: body.data,
    meta: body.meta ?? {},
  }
}

/** First error message for a field, or for the form when no field is given. */
export function authError(result: AuthResult | null, param?: string) {
  if (!result) return undefined
  const match = result.errors.find((e) => (param ? e.param === param : !e.param))
  return match?.message
}
