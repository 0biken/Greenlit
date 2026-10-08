# Sign-in

How accounts, sessions and two-step verification work (TASKS M1-07, SEC §3, decision record 012). Tests: `tests/security/test_auth_flows.py`, `test_mfa.py`, `test_auth_surface.py`.

## How the app talks to it

The React app uses allauth's headless JSON API under `/_allauth/browser/v1/`. It first calls `GET /_allauth/browser/v1/config`, which sets the CSRF cookie and lists what is switched on. Every later request sends the `X-CSRFToken` header. allauth's own HTML pages are switched off (`HEADLESS_ONLY`); `/accounts/` stays only for the Google callback.

| Step | Call | Result |
| --- | --- | --- |
| Sign up | `POST /auth/signup` `{email, password, name}` | 401 with flow `verify_email` pending; a confirmation email is sent |
| Verify | `POST /auth/email/verify` `{key}` (the key in the emailed link) | Verified, but not signed in |
| Sign in | `POST /auth/login` `{email, password}` | 200 signed in, or 401 with flow `mfa_authenticate` |
| Second step | `POST /auth/2fa/authenticate` `{code}` (an app code or a recovery code) | 200 signed in |
| Enrol | `GET /account/authenticators/totp` then `POST` with a code | The `GET` returns the secret and an `otpauth://` link to show as a QR code |
| Recover | `POST /auth/password/request`, then `POST /auth/password/reset` `{key, password}` | Same answer whether or not the address is registered |
| Change password | `POST /account/password/change` | Every other session ends |
| Sign out everywhere | `POST /api/sessions/end-all/` | Every session ends, this one too |
| Who am I | `GET /api/me/` | User, `mfa_enabled`, and per membership `needs_mfa` |

Email links point at the front end: `/verify-email/{key}` and `/reset-password/{key}` (`HEADLESS_FRONTEND_URLS`). The key is URL-encoded in the email.

## Rules

- **Passwords:** at least 12 characters, not on the common list, not numeric only, not in a known breach (Pwned Passwords range API; only a 5-character hash prefix leaves the server; fails open), stored with Argon2id.
- **Verified email:** required before anyone can sign in. An invitation can be accepted only by an account that has verified the invited address.
- **Lockout:** 5 failed attempts in 15 minutes lock that address and that IP. Even the right password is refused during the lockout, and a successful sign-in does not reset the count. The account holder gets one warning email per window; an unregistered address gets nothing and sees the same responses.
- **Sessions:** 12-hour idle timeout (renewed by each request) and a 30-day maximum from sign-in. Cookies are HttpOnly and SameSite=Lax; Secure outside development.
- **Reset links:** valid for 30 minutes, single use.
- **Two-step verification:** authenticator app (TOTP) plus 10 one-time recovery codes. **Owners and admins must enrol** (`ENFORCE_MFA_ROLES`): until they do, every organisation endpoint answers 403 `{"code": "mfa_required"}`. `/api/me/`, creating or joining an organisation, and the enrolment calls stay open, so a new owner can get set up. The secret is stored encrypted (Fernet).
- **Google:** the sign-in is built and tested with a stand-in; see below. A Google account is never silently attached to an existing password account with the same address.

## Settings to provide

| Variable | Purpose |
| --- | --- |
| `FIELD_ENCRYPTION_KEYS` | Comma-separated Fernet keys; the first encrypts, all decrypt, so keys can rotate. Required outside development (`manage.py check` fails without it). Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | From a Google Cloud OAuth client. Add the redirect URI `{API origin}/accounts/google/login/callback/`. Not done yet, and sign-in with Google cannot work until it is |
| `ENFORCE_MFA_ROLES` | Roles that must enrol. Default `owner,admin` |
| `BREACHED_PASSWORD_CHECK` | Default on; off in local development |
| `NUM_PROXIES` | Trusted proxies in front of Django; used for both API throttles and sign-in limits |
| `FRONTEND_URL` | Base of the links in emails |

## Local development

Owners and admins must enrol even locally. In the console email output, find the verification link; enrol with any authenticator app, or compute a code with `tests/support.py::totp_code`. Tests switch enforcement off in `config/settings/test.py` and switch it on again where they cover it.
