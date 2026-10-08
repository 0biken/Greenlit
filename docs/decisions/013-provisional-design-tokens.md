# 013. Provisional design tokens until the brand guidelines arrive

State: proposed (agreed in conversation, 2026-10-08)

## Context

Every spec says colour, type and status marks come from the Greenlit brand guidelines v2.0, but that document is not in the repository; only the logo pack is. The front-end shell (M1-18) cannot wait for it without stalling M1.

## Decision

Keep every colour, font, spacing and shadow value in one file, `web/src/design/tokens.css`, marked PROVISIONAL. Seed it from the logo (near-black ink, the green of the tick, a paper background). Components may use only those tokens, never literal values. Status is always a mark plus a word, never colour alone, so a palette change cannot break meaning.

When the guidelines are added (TASKS P0-04), replace the values in that one file and re-run the contrast test.

## Revisit when

The brand guidelines are added to the repository.
