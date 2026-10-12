# Reminders, critical alerts and the daily digest

What Greenlit tells people, and when (FR-INB-02, FR-INB-03, FR-DEF-05; TASKS M6-05 to M6-07, M5-07). Code: `api/apps/inbox/reminders.py`, `api/apps/inbox/jobs.py`. Tests: `api/apps/inbox/tests/test_reminders.py`.

## What is sent

| Trigger | Who is told | How |
| --- | --- | --- |
| A fix has waited for its retest past the first escalation time (48 hours by default) | The defect's owner | A notification record; the item is flagged as overdue and sits at the top of their Inbox. No email: the digest carries it |
| Past the second time (96 hours) | The project's QA leads, admins and owners | The same, and the item now appears in their Inboxes too |
| A defect is closed while its last retest had failed | Owner and the project's leads | A notification record **and an email at once**. This never waits for the digest |
| 07:00 in a person's own time zone, if anything is open for them | That person | One email listing what is in their Inbox |

The two escalation times are per project (`retest_escalation_hours` in the project settings).

## Told once

Every notification is first written to `inbox.notification`, which is unique per person, level, record and cycle. If the row already exists, nothing is sent. That is what makes the jobs safe to run twice, to overlap, or to be retried.

`cycle` separates one wait from the next. For a defect it is when the current wait began, so a defect that fails its retest, is fixed again and waits again is reminded again. For a digest it is the person's local date.

An email is sent when the surrounding work commits, after its row is written. If sending fails after that, it is not retried that day: at most once, rather than possibly twice.

## What a digest contains

IDs, titles, ages and links, grouped the way the Inbox groups them. Never steps, expected or actual text, requirement text or anything from a document (SEC §10). Snoozed items are left out. Nobody with an empty Inbox gets a digest.

It is sent between 07:00 and 10:00 local time, so a late or retried job still delivers it but nobody is emailed in the afternoon. An unknown time zone falls back to UTC.

## Jobs and schedule

| Job | Schedule (`CELERY_BEAT_SCHEDULE`) | Does |
| --- | --- | --- |
| `reminders` | Every 15 minutes, once per organisation | Escalations and critical alerts |
| `digest` | Hourly, once per organisation | Sends to whoever's local time has reached 07:00 |

Closing a defect whose retest failed also queues `reminders` for that organisation straight away, so the alert does not wait up to 15 minutes.

Both run through the job framework (docs/jobs.md): one organisation at a time, inside its scope.

## Limits today

- **No email provider is chosen yet (D-009).** Locally, emails print to the console of whatever runs the job.
- **The schedule needs Redis, a worker and `celery beat`.** Without them (the local setup has none), nothing runs on a timer; the job that closing a defect queues runs inline.
- A person who belongs to two organisations gets one digest per organisation, because each job works on one organisation.
- There is no in-app notification list yet; `read_at` is unused.
- Links in emails to test cases and requirements lead to screens that are not built yet.
