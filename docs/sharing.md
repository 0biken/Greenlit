# PDF export and share links

How a signed release report leaves Greenlit (FR-RPT-04, SEC §4; TASKS M8-07, M8-08). Code: `api/apps/reports/pdf.py`, `api/apps/reports/sharing.py`. Tests: `api/apps/reports/tests/test_sharing.py`.

## The rule

Both the PDF and a share link show **the signed version only**: the report body stored at sign-off and the sign-off record. They never read live data, so what a client receives cannot change after the fact. A release that is not signed off has no PDF and cannot be shared.

## PDF

| Call | Who |
| --- | --- |
| `GET /api/projects/{key}/releases/{version}/report.pdf` | Anyone on the project |
| `GET /api/shared/{token}/report.pdf` | Anyone holding a share link |

- Laid out as the brand's ledger page: section numbers and status marks in a margin column, hairlines, and a sign-off box with the name, the date, readiness at sign-off and the full reason.
- The same signed report always produces the same bytes, so a file can be compared with a later download.
- Fonts are the PDF's built-in serif, sans and mono (the brand's stated fallbacks). Embedding Newsreader and IBM Plex needs their TTF files in the repo.

## Share links

| Call | Who | Notes |
| --- | --- | --- |
| `POST .../releases/{version}/share-links/` | Owners, admins, QA leads | Optional `days` (1 to 365, default 30). The answer contains the token **once** |
| `GET .../releases/{version}/share-links/` | Anyone on the project | State (active, expired, revoked), who made it and when. Never a token |
| `DELETE .../share-links/{id}/` | Owners, admins, QA leads | Revokes at once |
| `GET /api/shared/{token}/` | Anyone holding the link | The signed report, sign-off, and the blockers and coverage at sign-off |

The web address people pass around is `{FRONTEND_URL}/shared/{token}`, a page that needs no sign-in.

## How it is kept safe

- **Only a hash of the token is stored** (`share_link.token_hash`), the same as invitations. A database leak does not leak working links, and a lost link cannot be recovered: make a new one.
- **Unknown, expired and revoked tokens all answer 404**, so a guess learns nothing.
- **Finding the link before any organisation is known.** The table's row-level policy lets a row be read either inside its organisation or by presenting the exact hash of its token (`app.invite_hash`, the mechanism invitations use). Without the token, a connection with no organisation sees no links at all. The view then continues inside that link's organisation, the way a background job does.
- **Every view and download is audited** against the link (`share_link.viewed`, `share_link.downloaded`), along with creation and revocation.
- The two public routes carry the `TokenAccess` policy marker (`apps/core/policy.py`), so the permission and isolation suites know they are deliberately open to token holders and check that they answer 404 without one. They are throttled per IP like every other route.
