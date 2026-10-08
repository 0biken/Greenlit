# Security headers, CSRF and rate limits

What the API sends and enforces (TASKS M1-16, SEC §8). Tests: `tests/security/test_hardening.py`.

## Headers on every Django response

| Header | Value | Why |
| --- | --- | --- |
| Content-Security-Policy | `default-src 'none'`, scripts and styles from `'self'` (plus a nonce when a template uses one), `frame-ancestors 'none'`, `base-uri 'none'`, `object-src 'none'`, `form-action 'self'` | Django serves JSON and the admin; it needs almost nothing |
| X-Content-Type-Options | `nosniff` | Stops a browser guessing a type for an upload |
| X-Frame-Options | `DENY` | Same as `frame-ancestors 'none'`, for old browsers |
| Referrer-Policy | `same-origin` | URLs carry display IDs |
| Permissions-Policy | `camera=(self)`, everything else off | The camera is needed to photograph a retest on a phone |
| Cross-Origin-Resource-Policy | `same-origin` | |
| Strict-Transport-Security | 2 years, subdomains, preload (production only) | |

Django adds a CSP nonce to the header only when a template uses it, so JSON responses have none.

## The single-page app needs its own policy

The React app's HTML is served by whatever hosts it (hosting is still open, D-007), so that host must send a policy for the HTML. Start from:

```
default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:;
font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none';
form-action 'self'; object-src 'none'
```

Add `blob:` to `media-src` only if evidence preview needs it. Do not add `'unsafe-inline'` or `'unsafe-eval'`. If the app and the API are on different origins, `connect-src` must name the API origin, and that origin must be in `CSRF_TRUSTED_ORIGINS`.

## CSRF

State-changing API calls (anything but GET) need the token. The app calls `GET /api/csrf/` once, which sets the `csrftoken` cookie and returns the token, then sends it back in an `X-CSRFToken` header. A request without it is refused with 403 "CSRF Failed". `tests/security` checks this for every non-GET endpoint it finds, so a new endpoint cannot skip it.

## Rate limits

Every API view is limited by address, by user and by organisation. The counters are in the cache (Redis in staging and production, in-process memory on a developer machine; decision record 011) and hold no tenant data.

| Scope | Default | Applies to |
| --- | --- | --- |
| ip | 1200 per minute | every request, signed in or not |
| user | 600 per minute | signed-in requests |
| org | 3000 per minute | everyone acting in one organisation |
| upload | 120 per hour | per user; attach `UploadThrottle` to file endpoints |
| ai_job | 60 per hour | per organisation; attach `AiJobThrottle` to AI endpoints |

Over the limit, the API answers 429 with a `Retry-After` header.

**Behind a proxy**, set `NUM_PROXIES` to the number of trusted proxies in front of Django. At the default of 0 the `X-Forwarded-For` header is ignored, so a caller cannot dodge the limit by faking it; with a proxy and the default, every caller would share the proxy's address.

Sign-in has its own, stricter limits (5 failures in 15 minutes per account and per address), set up with sign-in in M1-07.
