# The AI layer

How Greenlit asks a model for drafts, checks what comes back and keeps count (AI spec §2 to §9; ARCH §4; TASKS M2-04, M2-05). Code: `api/apps/ai/`. Tests: `api/apps/ai/tests/`, `api/apps/sources/tests/`.

## The one rule

**Only `apps/ai/client.py` calls the model provider.** A feature asks it for a draft and gets back a reply that already matches the feature's schema. Nothing the model says becomes a record on its own: it becomes a draft, and a person accepts or rejects it.

## What happens on a call

`client.run(feature, org_id=..., document=..., existing=[...])`:

1. **Reuse.** If this organisation already has an answer for the same feature, prompt version and input, that stored answer is returned and nothing is spent.
2. **Allowance.** If the organisation has used its allowance for the month, the call is refused with the message from AI §9. Nothing else in Greenlit is affected.
3. **Request.** The rules come first. Then this organisation's own records the model should know about (IDs and titles only), then the document, each in its own delimited section. The rules say that text in those sections is data and is never to be followed. The model is given no tools.
4. **Reply.** It must be JSON in the feature's schema. A reply outside the schema is asked for once more, then given up: it is never patched. A provider that cannot be reached is tried three more times with growing waits.
5. **Metering.** Every call writes an `ai_call` row: feature, model, prompt version, tokens in and out, cost, duration, a hash of the input, the outcome and the reply.

The caller then runs the checks, because only it knows its own records.

## Checks (`apps/ai/checks.py`)

| Check | If it fails |
| --- | --- |
| Reply matches the schema, with no extra fields | Asked once more, then the job fails with "AI drafting is unavailable right now. You can add items by hand." |
| A cited record ID exists in this project | The item is dropped |
| The quote is 5 to 30 words | The item is dropped |
| The quote is in the stored text word for word (only whitespace may differ) | The item is dropped |
| An image region lies inside the image | The item is dropped (used from F3 on) |
| Title up to 120 characters, up to 20 steps | The item is dropped and counted, never cut |
| Nearly the same as an existing record | Kept, marked as a possible duplicate |

Dropped items are stored in `ai_dropped_item` with the reason, for quality review. The person sees a count: "12 drafts created. 3 were left out because their source could not be confirmed."

## Drafts and decisions

`ai_draft` holds, for each drafted record, what the AI flagged (vague, possible duplicate, assumptions) and what a person decided: accepted or rejected, by whom, when, an optional reject reason, and whether an accept took under two seconds. One table serves every kind of record AI can draft. The count of fast accepts is shown to QA leads, admins and owners only. At most 20 drafts can be accepted in one action.

## Allowance (`apps/ai/usage.py`)

- A credit is `AI_TOKENS_PER_CREDIT` tokens (default 1,000). Reused answers cost nothing.
- The period is the calendar month.
- The limit is `organisation.ai_allowance`, or `AI_DEFAULT_ALLOWANCE` (default 2,000) when that is 0.
- At 80%, owners and admins are emailed once a month. At 100%, new AI work stops until the next month.

These three numbers are stand-ins until real costs are measured (AI §8).

## Logs

Logs and error reports from this layer carry IDs, hashes, outcomes and counts. Document text and model output are stored in tenant tables under row-level security and are never logged.

## Adding a feature

1. Add a `Feature` to `apps/ai/features.py`: its instructions and its schema.
2. Add its check to `apps/ai/checks.py`.
3. Write a job in the feature's own app that calls `client.run`, runs the check, saves drafts with `review_state = draft` and `origin = ai`, and calls `drafts.note_draft`.
4. The draft review screen and `ai_draft` are shared.

## Limits today

- **No real provider (D-008).** `AI_PROVIDER` defaults to `apps.ai.providers.StubProvider`, which drafts requirements by rule from the document's own sentences (those with must, can, should, will and similar). It makes the whole flow real, but it is not a model: it does not split compound statements or judge importance well.
- **No quality scores yet.** The eval runner (M2-10) and the 30-document injection pack (M2-11) need a real provider and the Phase 0 test set. Today six hostile documents test the checks layer only.
- Only F1 (requirements from a PRD) is built. F2 to F5 are later tasks.
