# 012. Sign-in through allauth's headless API

State: proposed (assumption in the build plan, 2026-10-08)

## Context

The front end is a React single-page app (decision 003). Sign-in needs email and password with verified email, Google, authenticator-app 2FA, recovery, and session control (SEC §3). The architecture already chose django-allauth.

## Decision

Use `allauth.headless` (browser client) with `allauth.mfa` and `allauth.usersessions`. The SPA calls allauth's JSON endpoints under `/_allauth/browser/v1/` with the session cookie and a CSRF token. Server-rendered allauth pages are not used; `accounts/` stays mounted only for the Google provider callback.

Greenlit adds only what allauth does not provide: the breached-password check, the lockout email, a 30-day absolute session limit, and the rule that owners and admins must enrol in 2FA before using an organisation.

## Revisit when

An enterprise customer needs SSO (phase 3), or allauth's headless API changes incompatibly.
