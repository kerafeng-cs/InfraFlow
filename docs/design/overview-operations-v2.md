# Overview for operators

The first screen answers four questions in order: what needs review, what is still running, how current is the observation, and where should the operator go next. It does not claim that a requested state is the observed result.

## Information order

1. **What needs attention:** blocked or unknown Environment; latest failed or blocked Operation; active Operation beyond its action-specific deadline; active Lease expiring within seven days; active Environment not observed within 15 minutes. Each item links to its detail page. An old failed Operation does not remain urgent after a later success. Reclaimed Leases do not produce expiry alerts.
2. **Freshness and counts:** show how many active Environments were observed within 15 minutes and when this page last fetched data. The controller's scheduled reconciliation is every five minutes; the 15-minute threshold is a review signal, not proof of failure.
3. **Operations in progress:** show the recorded action, status and elapsed time. There is no percentage progress because the API has no measured completion percentage.
4. **Fleet and deadlines:** a status distribution and Lease expiry buckets help compare the current portfolio. The deployment table gives direct navigation.
5. **Context below the fold:** recent Operation records and three cost scenarios. Cost is an estimate for active Leases since each Lease began, not an AWS bill. Different Leases may cover different periods, which is disclosed beside the chart.

## Refresh and incomplete data

The operator may refresh manually. While the page is visible and no control is focused, it refreshes every 60 seconds. Detail, operation and cost requests are independent: one failed request must not erase the rest. Incomplete sources produce a warning and must never produce an unqualified all-clear message.

## Visual approach

The layout uses the existing InfraFlow light cloud dashboard tokens. The action list leads with restrained red only when there is an issue. Counts, operation status and links carry meaning without decorative charts. Desktop uses compact two-column data panels; mobile stacks panels in task order. The status donut and expiry bars are summaries of discrete current values. No historical line chart is shown because the API exposes only recent Operation records, not a complete time series.

## Verification

`python -m unittest discover -s web/tests -v` covers desktop and mobile with mocked API responses for urgent states, active progress, freshness, recovered failures and reclaimed Leases. The service suite and JavaScript syntax checks are separate. AWS behavior remains unverified locally.
