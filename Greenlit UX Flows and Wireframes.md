# Greenlit UX Flows and Wireframes

Oct 4, 2026 ·&#32;

## Overview

Greenlit v1 has 11 main screens, and the QA Inbox is the home screen: users land on what needs them, not on a dashboard of charts. This doc covers the three core flows and wireframes for the three screens that carry the most risk.

Wireframes here are layout and content only. Colour, type and status marks come from the Greenlit brand guidelines v2.0 (ink and paper, green only for verified or ready, pen marks for status).

**Design rules**

1. **Open work first.** Every list sorts what needs action to the top, with its age.
2. **IDs everywhere.** Every record shows its display ID (BUG-1042), and IDs are clickable wherever they appear.
3. **Source beside draft.** AI drafts are always reviewed next to the passage or screenshot they came from.
4. **Status is a mark plus a word.** Never a colour alone.
5. **One primary action per screen.** It is ink; only sign-off is green.
6. **Keyboard first for daily work.** Recording results, accepting drafts and moving through the Inbox all have shortcuts.

## Navigation map

The top bar has three items: Inbox, Projects and Settings. Everything else lives inside a project, in the order work usually happens.

*Text version; the original diagram was lost when this document was exported. Reconstructed from the rest of the specs, so check it against the source diagram.*

| Area | Screens |
| --- | --- |
| Top bar | 1. Inbox · 2. Projects · 3. Settings (organisation, members, project settings, AI usage) |
| Inside a project, in working order | 4. Project home · 5. Sources (PRDs, screenshots, old reports) · 6. Requirements · 7. Draft review · 8. Test plans (versions, diff, rollback) · 9. Test runs · 10. Defects (list and detail, retest) · 11. Releases (readiness, report, sign-off) |

## Flow 1: PRD to approved plan

A QA engineer turns a PRD into a reviewed plan in one sitting; the QA lead's approval publishes it as version 1.0.

*Text version; the original diagram was lost when this document was exported. Reconstructed from the rest of the specs, so check it against the source diagram.*

1. The QA engineer uploads a PRD or pastes its text on the project's Sources screen.
2. Greenlit extracts draft requirements, showing progress by section.
3. The engineer reviews the requirement drafts beside their passages and accepts, edits or rejects each one.
4. The engineer asks for test cases on the accepted requirements; Greenlit drafts them.
5. The engineer reviews the case drafts. Uncovered requirements and the AI's gaps list are shown.
6. The engineer submits the plan for approval.
7. The QA lead reviews and approves it, which publishes version 1.0.

Both review steps use the draft review screen (wireframe below). The gaps the AI finds are shown as a list of questions the engineer can copy to the product team.

## Flow 2: run to verified fix

A tester records a failure, attaches evidence and files a defect in three keystrokes or clicks. The defect then comes back to them as Needs retest once a developer marks it fixed.

*Text version; the original diagram was lost when this document was exported. Reconstructed from the rest of the specs, so check it against the source diagram.*

1. In a run, the tester marks a case Failed (`F`).
2. They attach evidence by paste or drag and drop (`E`).
3. They select **Create defect**. It is pre-filled with the case's steps and the evidence, and linked to the run and case.
4. A developer sets the defect to Fixed. It appears in the tester's Inbox as Needs retest.
5. The tester retests with evidence. A pass makes it Verified. A fail makes it Retest failed and sends it back to the developer.

On a phone, the retest step opens the camera for evidence directly, so a fix can be checked on a real device in under a minute.

## Flow 3: release sign-off

The QA lead signs off from the release page, and the screen makes it hard to sign off without seeing what is still open. Signing off while not ready is allowed, but always recorded with a reason.

1. The QA lead opens **Releases › 2.4.1**. The readiness panel shows Ready or Not ready yet, with blockers grouped and counted.
2. Each blocker links to its record. Fixing or retesting it updates the panel without a page reload.
3. The lead selects **Draft release report**. The AI draft opens beside the facts it used, each claim linked to its run or defect.
4. The lead edits the report and selects **Sign off release 2.4.1** (the only green button in the product).
5. If readiness is Not ready yet, a dialog lists the blockers and requires a written reason before the sign-off button becomes active.
6. Sign-off freezes the report, records the name, date and readiness at that moment, and offers **Download PDF** and **Copy share link**.

## Wireframe: QA Inbox

The Inbox is one list grouped by urgency, across all the user's projects, with one action per row. Critical items sit on top in their own band.

*Wireframe image not included in this export.* Layout: a left sidebar lists the Inbox groups (FR-INB-01) with counts and a Snoozed filter; the main column holds a critical band on top, then rows grouped by urgency.

- Each row: status mark, ID, title, project, age, and the single next action (Retest, Run, Add case, Open).
- Rows can be snoozed with a reason from a row menu (not shown); snoozed items move to the Snoozed filter.
- On a phone the sidebar becomes a filter chip row at the top, and project and age move under the title.

## Wireframe: draft review

The source sits on the left and the draft on the right, so a reviewer checks each draft against its passage without switching screens. The goal is a decision in under 10 seconds per draft.

*Wireframe image not included in this export.* Layout: the source document or screenshot on the left with the cited passage or region highlighted; draft cards on the right, each with Accept, Edit and Reject, its assumptions, and the gaps list at the end.

- Blue pencil and the word Draft mark everything not yet accepted.
- Assumptions the AI made are shown on the card, never hidden.
- Accept-all works on at most 20 drafts at a time (AI behaviour spec, section 6).

## Wireframe: release readiness and sign-off

Blockers sit on the left, where the lead's eye lands first; the report and the sign-off sit on the right. The override dialog (shown open) appears only when the release is not ready.

*Wireframe image not included in this export.* Layout: readiness and blockers grouped with counts on the left; the report draft and the green sign-off button on the right; the override dialog listing blockers above a required reason field.

- **Sign off anyway** stays disabled (dashed) until a reason is typed.
- The sign-off button is the only green control in the product.
- After sign-off, the report freezes and the page shows who signed, when, and the readiness at that moment.

## Empty, loading and error states

Every screen has a designed empty, loading and error state, written in the brand voice. An empty screen always says what to do next.

| Screen | Empty | Loading | Error |
| --- | --- | --- | --- |
| QA Inbox | "Nothing needs you right now." plus the next scheduled release | Skeleton rows in the real layout | "Couldn't load your Inbox. Retry." with the last loaded copy shown |
| Project, first visit | "Start with a PRD, screenshots, or an old QA report." with three upload buttons | n/a | n/a |
| AI drafting | n/a | Progress by section, drafts appearing as ready; user can leave and is notified | Plain cause and the manual alternative (AI behaviour spec, section 9) |
| Test run | "No cases in this plan version yet." with a link to the plan | Skeleton | Results that failed to save stay marked and retry automatically |
| Defects | "No defects on this project." | Skeleton | Retry, with filters kept |
| Release | "No runs linked yet. Start a run from a plan version." | Readiness shows "Checking…" | Readiness shows "Couldn't check" and blocks sign-off |
| Upload | n/a | Per-file progress bar | "This file type isn't supported here. Use {accepted types}." The types depend on the upload kind (PRD v2, section 9), for example "Use PDF, DOCX or Markdown." for a PRD |

Offline or slow connections: results being recorded in a run are saved locally first and sent when the connection returns, with a visible "Saving…" or "Saved" marker.

## Accessibility and responsive rules

Greenlit targets WCAG 2.2 AA, and the QA Inbox and retest flow must work on a phone. Full test running and plan editing are desktop-first.

| Area | Rule |
| --- | --- |
| Keyboard | Every action reachable by keyboard; visible focus ring; shortcuts listed under `?` |
| Run shortcuts | `P` passed, `F` failed, `B` blocked, `N` not run, `E` attach evidence, arrow keys to move between cases |
| Draft review shortcuts | `A` accept, `R` reject, `Enter` edit, `J` / `K` next and previous |
| Screen readers | Status chips read as "Status: Needs retest, 4 days"; marks have text labels; live regions announce saved results |
| Colour | Status always pairs a mark and a word; contrast ratios from the brand guide |
| Motion | No essential animation; respects reduced-motion settings |
| Breakpoints | Phone under 640 px: Inbox, defect detail, retest with camera upload. Tablet 640 to 1024 px: everything readable, editing simplified. Desktop 1024 px and up: full product |
| Touch | Targets at least 44 by 44 px on phones |

## Open questions for usability testing

Test these with 5 QA engineers and leads during phase 0, using clickable mock-ups of the three wireframed screens.

- [ ] Do users understand the difference between Closed (tracker) and Verified (Greenlit) without explanation?
- [ ] Is the Inbox the right home screen, or do leads want a project overview first?
- [ ] Can a reviewer judge a draft test case in under 10 seconds with the source beside it?
- [ ] Do the run keyboard shortcuts feel natural, or do testers prefer clicking?
- [ ] Does the sign-off override dialog feel protective or obstructive?
- [ ] On a phone, can a tester retest a fix and attach a photo as evidence in under a minute?
