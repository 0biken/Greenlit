# Sources and draft review

How a PRD becomes reviewed requirements (FR-PLAN-01, FR-PLAN-02, FR-PLAN-04; AI §3 F1, §5, §9; UX §7; TASKS M2-01 to M2-03, M2-06, M2-07, M2-09). Code: `api/apps/sources/`, `web/src/features/sources/`. Tests: `api/apps/sources/tests/`. The AI layer itself is in docs/ai.md.

## The path

1. **Add a source.** Upload a PDF, DOCX, Markdown or plain-text file with kind `prd` through the file service, or paste the text.
2. **Scan.** An uploaded file is checked by `scan_file` as every file is.
3. **Parse.** `parse_source` reads the text and stores it with where each page and section sits in it (`source_extraction`). Pasted text is read at once.
4. **Draft.** `draft_requirements` sends one section at a time to the AI client, checks each reply and saves what passes as requirements with `review_state = draft` and `origin = ai`. Drafts appear as each section finishes.
5. **Review.** A person accepts, edits or rejects each draft. Only accepted requirements count towards coverage, readiness and reports, and only they can be linked to a test case.

## Calls

| Call (under `/api/projects/{key}/`) | Who | Does |
| --- | --- | --- |
| `GET sources/` | Anyone on the project | The project's sources with state, progress and draft counts |
| `POST sources/` | Testers | `{file_id, title?}` for an uploaded PRD, or `{title, text}` for pasted text |
| `GET sources/{id}/` | Anyone | The text by page, the drafts with where each is stated, the gaps list, how many drafts were left out, job progress |
| `POST sources/{id}/draft/` | Testers | Draft again. Passages that already have a draft are skipped; unchanged text is not paid for twice |
| `POST sources/{id}/accept/` | Testers | Accept up to 20 drafts at once |
| `POST requirements/{id}/review/` | Testers | `{decision: accepted or rejected, reason?, viewed_ms?}` |

"Testers" are owners, admins, QA leads and QA engineers. A drafted requirement is edited with the ordinary requirement `PATCH`; it stays a draft and keeps its source.

## Where a draft came from

Each drafted requirement stores `source_document` and a `source_locator`: the page and the character positions of its quote in the stored text. The review screen highlights exactly that passage. When a requirement's text later changes, the old locator stays with the old revision in `requirement_revision`.

## The review screen

The source text is on the left with the current draft's passage highlighted. Drafts are on the right, each with the blue-pencil mark and the word Draft.

| Key | Does |
| --- | --- |
| `A` | Accept the current draft |
| `R` | Open the reject reasons; `R` again rejects without one |
| `Enter` | Edit the current draft |
| `J`, `K` | Next and previous draft |

The gaps list ("Questions for the product team") can be copied. The source is shown as extracted text by page, not as the original PDF pages.

## What people are told when it goes wrong

| Situation | Message |
| --- | --- |
| The provider cannot be reached, or answers outside the schema twice | "AI drafting is unavailable right now. You can add items by hand." |
| Some drafts failed a check | "12 drafts created. 3 were left out because their source could not be confirmed." |
| The allowance is used | "Your AI allowance for this month is used. Drafts resume on 1 November, or an owner can top up." |
| A PDF with no selectable text | "This PDF has no text Greenlit can read. Paste the text instead." |
| More than 200 pages | The page count and the limit |

In every case the document is kept and requirements can still be added by hand.

## Limits today

- **No OCR.** A scanned PDF is refused with the message above.
- **PDF sections are pages.** Headings in a PDF cannot be told from body text reliably, so each page is one section. Markdown and DOCX use their headings.
- **DOCX pages are by length**, about 3,000 characters each, because Word files do not store page breaks in a readable way.
- **Progress is polled** every two seconds (D-010 is open). Locally there is no worker, so drafting finishes inside the request that started it and progress is never seen moving.
- Only PRDs are sources so far. Screenshot sets and old QA reports are M7.
