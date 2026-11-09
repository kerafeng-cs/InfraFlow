# InfraFlow Console Visual v2 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task. Preserve the existing product behavior and verify each visual state.

**Goal:** Give InfraFlow a coherent, readable operations-console identity across management, sign-in and public Wake pages.

**Architecture:** Keep vanilla HTML/CSS/JS and the existing API. Establish semantic visual tokens and layout rules in `web/style.css`; make only small markup changes required for hierarchy and accessibility. Use a single authored Superdesign draft for the Environments page as the visual reference, then verify actual browser renders.

**Tech Stack:** HTML, CSS, JavaScript, headless Chrome via Playwright for local visual checks.

**Spec:** `docs/design/infraflow-console-v2.md`; team Product UX/UI v1.0 in the shared InfraFlow checkout.

## Global constraints

- Keep Environments as the default route and the three separate surfaces: management, public Wake, Admin.
- Do not change API semantics or present ACCEPTED as completion.
- No paid generation, AWS mutation or deployment in this visual pass.
- Preserve the untracked baseline development plan.

## Review focus

- Login field and button must not touch, including the focus outline at 320–625px.
- Long names, status labels and identifiers must wrap or scroll intentionally.
- BLOCKED and operation states must remain distinguishable without color.
- Mobile navigation must be usable without hiding primary routes.
- Public Wake must remain free of private resource and owner data.

---

### Task 1: Design reference and tokens

**Files:** `.superdesign/design-system.md`, `.superdesign/init/*`, `docs/design/infraflow-console-v2.md`.

- [x] Map current source, routes, shared patterns and product constraints.
- [x] Import an authored Environments design to Superdesign without generation credits.
- [x] Check the imported document and rendered preview; draft `cea45fa6-475e-4416-bd84-55c4188de9a7` in project `2731882e-728f-4f6a-bfd7-db7ffc5b4b44`.

### Task 2: Shared visual system

**Files:** `web/style.css`, optionally `web/index.html`.

- [x] Refine header, typography, grid, panels, controls, tables and status treatments from the chosen draft.
- [x] Verify desktop and phone renders; fix the mobile BLOCKED accent after visual inspection.

### Task 3: Screen consistency

**Files:** `web/app.js`, `web/sleep.html`, `web/style.css`.

- [x] Align sign-in, Environments, Environment Detail, Lease, Admin, Create and public Wake hierarchy with shared tokens and layout.
- [x] Preserve controls and labels for error, empty, BLOCKED and in-progress states.

### Task 4: QA and handoff

- [x] Audit changed UI against current Vercel Web Interface Guidelines; make filter state restorable from the URL, add theme colors and correct form widths.
- [x] Run syntax and diff checks plus browser screenshots at 1440, 625, 375 and 320px.
- [x] Record design limits and leave a scoped commit on the UI branch.

## Limits of this pass

- The Superdesign canvas contains one authored Environments reference screen. Other screens were aligned in the real code through shared tokens and inspected in browser screenshots; they are not separate canvas drafts.
- Browser checks use mocked API responses. They prove layout and visible control behavior, not AWS or Cognito integration.
- The current API still lacks Register, ownership-classified inventory and a paginated Environment overview. This visual pass does not claim those capabilities.
- The team's baseline development plan remains untracked and untouched in this checkout.
