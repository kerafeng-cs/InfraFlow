# InfraFlow design system — workbench v3

Product: AWS Web + Database staging Environment operations console. User: Lease manager first, Admin second; public Wake is separate. Team Product UX/UI v1.0 remains the behavior authority.

Visual: quiet engineering workbench. A 228px light utility rail on desktop; a wide content surface for data; horizontal navigation at 900px and below. No dark SaaS header, colored logo square, decorative KPI tiles, gradients, floating cards or ornamental eyebrow labels.

Tokens: canvas #F8F9FA; surface #FFFFFF; rail #F3F5F6; ink #1D2733; muted #576472; line #DCE2E8; action #2156A0; success #126445; warning #8B510D; danger #A62D2D; focus #F2A900.

Typography: self-hosted IBM Plex Sans variable, Latin and Vietnamese subsets, OFL 1.1. Fallback Segoe UI/system sans. 15px body at 1.5 line height; 28–34px page title, 19px section title, 13px meta labels. Monospace only for identifiers. Avoid all-caps except compact table headings and state codes supplied by the API.

Layout: desktop rail width 228px, main horizontal padding 24–64px. Mobile 16px gutters and horizontal navigation. Panels have flat 1px borders, 3px corners or no outer border. Environment rows and status axes use rules, not repeated card containers.

Reusable patterns: AppRail, PageHeader, StatusBadge, StatusAxis, EnvironmentRow, ObservationStamp, ReviewBox, InlineError, PublicWakePanel. Buttons 44px minimum height. Focus outline 3px with clear control spacing. Loading/error/empty/BLOCKED states remain explicit.

Content: Environment, Lease, observed availability, desired level, operation, request accepted, verified outcome. Do not imply an operation completed from HTTP 202. Public Wake never includes private resources, owner or cost data.
