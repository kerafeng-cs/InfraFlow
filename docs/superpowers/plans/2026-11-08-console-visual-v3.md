# InfraFlow Workbench Visual Revision Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement and verify each task. Preserve the current product behavior.

**Goal:** Replace the generic dashboard look with a deliberate, readable operations workbench.

**Architecture:** Keep the existing HTML and API logic. Change the shared CSS layout and typography, package two local font subsets, update the existing Superdesign draft without generation credits, and verify actual browser renders.

**Tech Stack:** Vanilla HTML/CSS/JavaScript, IBM Plex Sans WOFF2, Playwright with Chrome.

**Spec:** `docs/design/infraflow-console-v3.md`; team Product UX/UI v1.0 remains the behavior source.

## Global constraints

- No new lifecycle behavior, status inference, AWS call or paid generation.
- Public Wake stays separate from management navigation and private details.
- Preserve the existing untracked baseline development plan.

## Review focus

- Desktop utility rail must not leave an empty rail on sign-in.
- 320px navigation and Environment rows must remain usable without page overflow.
- Font must render Latin and Vietnamese from local assets with system fallback.
- BLOCKED and running operations must retain textual evidence and distinct priority.
- Password focus outline and Sign in button must not touch.

---

### Task 1: Typography and layout

- [x] Package IBM Plex Sans Latin/Vietnamese WOFF2 and OFL license.
- [x] Replace dark top bar and initial-square mark with a quiet light utility rail on desktop and a horizontal mobile navigation.
- [x] Reduce repeated rounded cards; use table rows and ruled status facts.

### Task 2: Screen states

- [x] Give signed-out users a simple top brand band rather than an empty utility rail.
- [x] Keep Environment, Lease, Admin, Create and public Wake behavior intact.
- [x] Revise the Superdesign reference draft as version 2 through direct import; no generation credits used.

### Task 3: Quality checks

- [x] Check actual renders at 1440, 625, 375 and 320px, including BLOCKED and in-progress states.
- [x] Check local Latin and Vietnamese font loading, login focus spacing, JavaScript syntax, diff formatting and mocked UI flows.
- [x] Refresh Superdesign resume context, review the final diff, and commit only scoped design files.

## Limits

Browser checks use mocked API responses. Font and layout behavior were checked in headless Chrome; review with a real user and the staging API remains separate work.
