# InfraFlow console v4 — enterprise cloud dashboard

This revision implements the team's 2026-11-09 UI request for Sign in, Environments, Environment detail, and New Lease. The signed-in Overview is specified separately in `infraflow-overview-v1.md`. The product and API baseline remains v1.2. The v3 visual document is historical.

## Design system

- System font stack: Inter when installed, then platform UI fonts. Code and identifiers use a monospace stack. No runtime font download. The v3 font files remain in the repository for provenance but are no longer referenced or deployed.
- Background `#F8FAFC`, white cards, `#E2E8F0` borders, 12px card corners, and subtle shadows. Accent blue `#2563EB` / `#1E40AF`.
- Status pills show both text and a colored dot. Operation `RUNNING` uses amber; resource `RUNNING` uses green. Observed state, desired state, and operation result remain separate facts.
- Focus uses a visible blue ring. Navigation uses semantic links; day selection uses buttons with `aria-pressed` and a hidden form value.

## Screen behavior

1. Sign in: centered brand and 400px card, full-width primary action. A local preview without deployment configuration shows a connection message.
2. Environments: four KPIs from loaded Environment detail records, then one card containing filters and the table. If one or more Lease detail requests fail, the KPI note explicitly says counts are incomplete. The Sleeping KPI and filter both include `SLEEPING` and `ASLEEP:*`; the attention KPI includes `BLOCKED` and `UNKNOWN`.
3. Environment detail: observed/desired facts form a 2×2 grid even on mobile. Resource status pills and operation pills use separate color semantics. A submitted action remains a request until observation confirms the outcome.
4. New Lease: related fields form named sections. Seven day buttons preserve the existing comma-separated day value and API payload. Schedule permits an optional idle timeout; On demand requires it. The review receipt reflects the exact payload before provisioning starts.

## Verification boundary

Browser previews and flow checks use mocked API responses. AWS staging, Cognito sign-in, real resource observation, and user acceptance require separate verification. The static site does not call AWS directly.
