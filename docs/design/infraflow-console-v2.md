# InfraFlow Console v2 — visual and interaction design

**Source of truth:** team Product UX/UI v1.0 and current API contracts. This document refines presentation, not lifecycle permissions or verified outcomes.

## Audience and job

Lease managers need to find an Environment needing attention, understand observation versus request, and submit an allowed action with a clear outcome. Admins investigate BLOCKED cases. Public visitors only see safe Wake status.

## Structure

1. Keep one navigation shell across management pages. Environments remains the default route; Leases holds policy and expiry; Blueprint check and Admin are secondary.
2. Every management page starts with one title, one useful summary, and the main action for that page. Data follows in aligned sections rather than identical floating cards.
3. Environment rows prioritize name, observed state, desired state, operation, and observation time. BLOCKED/UNKNOWN remain visible without relying on color.
4. Environment Detail keeps status axes, next action, resources and operation history in that order. The API does not expose a verified per-step timeline or ownership classification, so do not draw one.
5. Create and Reclaim retain explicit review steps. A 202 response is “request accepted,” never completed.

## Visual direction

**Concept:** an operations instrument panel: a dark, stable navigation rail at the top; bright, calm working surface; crisp rules for rows; one blue action color; amber/red only where the state demands it. No decorative KPI tiles or gradients.

- Canvas `#F6F8FB`; surface `#FFFFFF`; navigation `#10233E`; primary text `#14243A`; secondary text `#51647C`; border `#D8E1EC`; action `#2458D3`.
- Typography: system UI with Segoe UI first on Windows; 15px body, 28–36px page title, 18–20px section title; monospace only for identifiers. Use tabular numbers for timestamps and costs.
- Desktop working area max 1240px, 24–32px gutters. Mobile has 16px gutters, full-width controls and readable labeled rows; navigation scrolls horizontally by design.
- Panels use borders and deliberate grouping with minimal shadow. Primary content is visually stronger than supporting descriptions; at most one prominent primary action per context.
- Focus ring remains high contrast and separated from adjacent controls by at least 12px. Buttons retain at least 44px touch height.

## Acceptance checks

- At 1440, 625, 375 and 320px: no accidental page overflow, clipped label, button overlap or obscured focus ring.
- Keyboard can reach navigation, forms, review controls and public Wake. Loading, error, empty, BLOCKED and operation states have text labels.
- No new browser-only authority: backend still decides permissions, safety and completion.
