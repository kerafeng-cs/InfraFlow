# InfraFlow Overview v1

The signed-in home route `#/` is an operations overview. The detailed Environment list is at `#/environments`; Leases remain at `#/leases`. Old filtered `#/?...` bookmarks are redirected to the Environment list. This design uses the visual system in `infraflow-console-v4.md`.

## Source and meaning

All counts and rows come from `GET /v1/leases`, scoped by the API to the signed-in organization. A Lease is the deployment unit. Its returned Environment summaries contain names and availability states but no Environment ID, observation time, resource inventory, performance metric, or operation history. The overview therefore links attention items to their Lease and never invents CPU, uptime, cost, or a verified completion result.

| Display | Definition |
| --- | --- |
| Total Leases | Number of returned Lease records |
| Environments | Sum of returned Environment summaries |
| Awake | Availability exactly `AWAKE` |
| Sleeping | `SLEEPING` or `ASLEEP:*` |
| Needs attention | Availability `BLOCKED` or `UNKNOWN` |
| Changing | Availability `CHANGING` |
| Other states | Returned Environments outside those groups |

The status donut uses those mutually exclusive groups; its text legend always shows counts, including zero groups. The expiry chart counts Lease expiry dates in four non-overlapping windows: date passed, next 7 days, 8–30 days, and later. Invalid or missing dates receive a separate "Date unavailable" row. Buckets are calculated from the browser's current time and show dates, not the lifecycle outcome of a Lease. The nearest future expiry links to its Lease.

The deployment table shows at most six Leases, ordered by attention count then expiry, with a link to the complete Lease list. The attention panel shows at most four Environment summaries, with a link to each parent Lease. KPI cards lead to the corresponding list or filtered Environment view.

## Empty and error states

With no Leases, counts are zero and the page offers Create Lease. If the list request fails, the page shows an error instead of zero counts. The overview does not run extra per-Lease requests or infer an Environment ID from its name. It has no historical CPU, uptime, cost, or incident series; no trend chart is shown without such a source.

## Verification boundary

Browser checks use mocked API responses and multiple viewport widths. The Overview still needs staging checks with real organization data and user acceptance before production use.
