# InfraFlow design system

Product: AWS Web + Database staging Environment operations console. User: Lease manager first, Admin second; public Wake is separate. Use the team's Product UX/UI v1.0 as behavior authority.

Visual: technical minimalism with a dark navy navigation bar and a calm light working area. Flat surfaces, crisp dividers, dense but breathable operational rows. No marketing hero, ornamental charts, glassmorphism, colorful tiles or unverifiable success claims.

Tokens: canvas #F6F8FB; surface #FFFFFF; nav #10233E; ink #14243A; muted #51647C; line #D8E1EC; action #2458D3; action hover #1747B4; success #126445; warning #8B510D; danger #AA2828; focus #F2A900.

Typography: Segoe UI / system UI for all interface text; 15px body at 1.5 line height; 28–36px page title; 19px section title; 13px meta labels. Monospace for IDs only. Keep status and timestamps legible without color.

Layout: desktop maximum width 1240px, 24–32px gutters; mobile 16px gutters. Header is one stable band, primary action aligned with page heading, sections aligned on the same grid. Table rows use rules, not floating cards; on mobile, rows become labeled blocks.

Reusable patterns: AppHeader, PageHeader, StatusBadge, StatusAxis, EnvironmentRow, ObservationStamp, ReviewBox, InlineError, PublicWakePanel. Buttons 44px minimum height. Focus outline 3px and visible spacing. Loading/error/empty/BLOCKED states are part of every relevant page.

Content: use actual InfraFlow terms: Environment, Lease, observed availability, desired level, operation, request accepted, verified outcome. Do not imply an operation completed from HTTP 202. Never show private resource details on public Wake.
