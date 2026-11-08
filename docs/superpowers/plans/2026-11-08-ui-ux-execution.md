# InfraFlow Console UI/UX Implementation Plan

**Goal:** Make the existing console and public Wake page understandable, consistent, accessible, and usable on desktop and phone while preserving the current API behavior.

**Spec:** The team's `2026-11-08-product-ux-ui-v1.md` design in the shared InfraFlow checkout; current API shapes in `services/infraflow/api.py`. The user explicitly chose to proceed with UI implementation without the previous Linear gate process. Backend Register and safety capabilities are separate work.

**Design tools:** Anthropic frontend-design for layout and copy, UI UX Pro Max for focused pattern lookup, Vercel web-design-guidelines for final audit. The approved product UX spec, not generated style recommendations, decides behavior.

## Constraints

- Do not add client-side claims of backend verification. `ACCEPTED` is a request, not completion.
- Use only current API fields; label unavailable management/ownership evidence as unavailable rather than inventing it.
- No AWS actions or deployment in this UI task.
- Keep public page free of private state, plan and resource identifiers.
- Preserve the existing Create, Sleep, Wake, Reclaim, Admin and blueprint-check routes.

## Task 1 — Shared visual and accessibility foundation

**Files:** `web/style.css`, `web/index.html`, `web/sleep.html`.

- [x] Establish restrained light-mode tokens, hierarchy, focus, responsive rules, semantic navigation and skip link.
- [x] Ensure `hidden` works with styled buttons and navigation.
- [x] Inspect desktop and 375px screenshots, including no page overflow.

## Task 2 — Lease list and current-detail cleanup

**Files:** `web/app.js`, `web/style.css`.

- [x] Make list empty/loading states actionable; keep state and time visible on phone.
- [x] Separate observed and desired labels, move Reclaim to a dedicated review section, and identify cost as estimated.
- [x] Add keyboard-submit sign-in/Create forms and accessible labels.

## Task 3 — Environment Detail and operation visibility

**Files:** `web/app.js`, `web/style.css`.

- [x] Link each Environment to a dedicated route using the existing GET Environment and Operations APIs.
- [x] Present management `status`, actual observation and desired state as separate axes with source/time; show operation status and outcome without false success. The current API has no reliable per-step progress field for this view.
- [x] Put allowed Wake/Sleep, URL, resources, history and refresh in clear sections. Blocked/terminal states do not expose mutation actions.
- [x] Verify with mocked ACTIVE, BLOCKED and in-progress responses at 1440px and 375px.

## Task 4 — Public Wake and Admin recovery

**Files:** `web/sleep.js`, `web/sleep.html`, `web/app.js`.

- [x] Public progress is text-only and resilient to network errors; no private data is rendered.
- [x] Admin has clear blocked/empty states, evidence timestamp and explicit recovery action wording; avoid an opaque prompt.
- [x] Verify public Wake and BLOCKED cases with a mocked browser session.

## Task 5 — Final audit and handoff

- [x] Re-read current Vercel guidelines; inspect changed files and fix material accessibility, copy, state and responsive defects.
- [x] Run JavaScript syntax checks, `git diff --check`, and mocked browser screenshots at desktop/phone sizes. Browser checks cover UI rendering and state controls, not AWS behavior.
- [x] Record remaining backend-dependent UX gaps below.
- [x] Review the whole diff and leave branch ready for user review. No push or deployment without a separate instruction.

## Backend-dependent follow-up

1. Add the product Register route and its owner/permission model; the current API only supports Lease creation and existing environment operations.
2. Expose explicit, verified lifecycle and ownership evidence from backend. Current Environment fields include `status`, `availability`, `actual`, `desired`, and timestamps, but do not prove owner approval or every intermediate resource step.
3. Expose operation stage progress through an API field if the detail page should show live step-by-step progress. Current operation history may include a plan, but it is not proof of executed stages.
4. Cost data is an InfraFlow estimate from unit prices and transition logs; AWS billed charges and residual resources need a separate source and UX treatment.
5. Review accessibility and copy with actual end users, and run the console against a connected staging API before release. Mocked browser responses cannot prove live behavior.
