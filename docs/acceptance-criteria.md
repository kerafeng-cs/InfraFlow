# Acceptance criteria

Each scenario states the required behavior and how the current implementation meets it.

| Status | Meaning |
|---|---|
| Covered | Enforced by design and exercised by an automated test. |
| Runtime | Enforced by design; verified only against a real AWS account. |
| Partial | Enforced for the main case; a known gap remains, described in the row. |
| Gap | Not handled yet. |
| Out of scope | Concerns registering existing environments, which is not supported. |

Test references are relative to `services/tests/`.

## Lifecycle

| ID | Scenario | Required behavior | Status | Evidence |
|---|---|---|---|---|
| L-01 | Create an environment from a certified blueprint | Resources are bounded to the instances of the blueprint and tagged with the Environment. | Covered | `test_flow.test_full_cycle`; Validator V1, V5, V8 |
| L-02 | Unsupported parameters or blueprint | Rejected with a validation error; no AWS action. | Covered | `test_flow.test_validation_and_idempotency` |
| L-03 | Sleep | Reaches the requested level; data and URL are preserved. | Covered | `test_ics.test_sleep_order_matches_design`, `test_flow.test_full_cycle` |
| L-04 | Wake | Database and application are running and healthy before DNS switches to the application. | Covered | `test_ics.test_wake_order_matches_design`, `test_bad_plan_dns_before_health_is_caught` |
| L-05 | Data survives repeated Sleep and Wake cycles | Rows written before Sleep are present after Wake, in every cycle. | Runtime | Demo app: notes and boot history persist across cycles |
| L-06 | Hibernate | The database is snapshotted and the snapshot is available before the database is deleted. | Covered | `test_ics.test_hibernate_snapshots_before_delete`, Validator V3 |
| L-07 | An environment that is already cheaper than the target | It is not woken in order to be put to sleep. | Covered | `test_ics.test_prepared_satisfies_sleep`, `test_flow.test_outside_schedule_only_prepares` |
| L-08 | Every pair of levels | The generated plan is safe under every interleaving. | Covered | C8 in `python -m infraflow.cli check`, `test_ics.test_web_db_passes_everything` |

## Data safety and plan scope

| ID | Scenario | Required behavior | Status | Evidence |
|---|---|---|---|---|
| D-01 | A plan deletes a data resource without a snapshot from the current operation | Rejected before execution and before apply. | Covered | A4 in the model checker, V3; `test_bad_plan_delete_db_without_snapshot_is_caught`, `test_v3_delete_db_without_snapshot` |
| D-02 | A plan replaces a data resource | Rejected. | Covered | V4; `test_v4_replace_db` |
| D-03 | A plan touches a resource of another Environment or outside the blueprint | Rejected; nothing is applied. | Covered | V1, V2, V6; `test_v1_v8`, `test_v2_instance_not_allowed`, `test_v5_v6_tags` |
| D-04 | The Terraform plan cannot be converted or parsed | Nothing is applied. | Runtime | The runner exits before `apply` when `terraform show` or the Validator fails |
| D-05 | The plan validated differs from the plan applied | Impossible by construction. | Runtime | The runner applies the same `plan.out` it validated, in the same job |
| D-06 | The root module was not produced by the certified compiler | Rejected. | Covered | V9 (`compiled_hash`); `test_ics.test_golden` |
| D-07 | A presence variable is missing | Terraform fails instead of removing infrastructure. | Covered | `test_ics.test_present_vars_have_no_default` |

## Public URL and health

| ID | Scenario | Required behavior | Status | Evidence |
|---|---|---|---|---|
| U-01 | Awake and healthy | The URL serves the application of this Environment only. | Runtime | `dns.point` after `elbv2.target_healthy` |
| U-02 | Asleep | The URL serves the sleeping page; no application origin is exposed. | Covered | `test_flow.test_full_cycle` (public status) |
| U-03 | A visitor requests Wake on a valid Lease | One operation starts, or the running operation with the same target is returned; progress is shown until the health gate passes. | Covered | `test_flow.test_full_cycle` |
| U-04 | Unknown host, expired or reclaimed Lease, blocked Environment | No cloud action; an explicit denial. Unknown and reclaimed hosts return the same response. | Covered | `_public_env`, `can_wake`; `test_flow.test_full_cycle` |
| U-05 | Repeated public Wake requests | Rate-limited per Environment; no duplicate operation. | Partial | 30-second rate limit and same-target deduplication. No per-client limit and no CAPTCHA. |
| U-06 | Health gate fails after Wake | DNS stays on the sleeping page; the Environment returns to sleep. | Covered | `test_flow.test_health_failure_puts_back_to_sleep`, `test_executor.test_health_failure_goes_to_failed` |
| U-07 | All targets become unhealthy while the Environment is awake | Traffic must not reach an unhealthy application. | Gap | An ALB forwards to all targets when none is healthy (fail-open), and DNS is not switched back. A periodic health check in reconciliation that switches DNS to the sleeping page is planned. |
| U-08 | DNS caches and open connections during Sleep | The application is not removed while clients still reach it. | Partial | DNS switches first, then a fixed 90-second drain precedes removal. Resolver propagation is not measured. |
| U-09 | Failure in the middle of Sleep or Wake | A safe path to `deep` and to `reclaimed` exists from every intermediate state; the Environment is blocked with a reason. | Covered | RESCUE check; `test_executor.test_stage_failure_blocks_and_skips_rest`, `test_flow.test_execution_error_blocks` |

## Concurrency and drift

| ID | Scenario | Required behavior | Status | Evidence |
|---|---|---|---|---|
| C-01 | Two requests with the same target | The second returns the running operation. | Covered | `test_flow.test_full_cycle` |
| C-02 | Requests with opposite targets | The second is rejected with `CONCURRENT_OPERATION`; nothing is queued. | Covered | `test_flow.test_full_cycle` |
| C-03 | Two writers on one Terraform state | Excluded by the Environment lock and the S3 state lock. | Runtime | Conditional write on `active_operation_id`; `use_lockfile` |
| C-04 | A resource changed outside InfraFlow (for example an instance started from the console) | Detected by observation and corrected by the next reconciliation. | Covered | `test_flow.test_drift_is_corrected_by_reconcile` |
| C-05 | RDS starts automatically after seven days stopped | Detected as drift and stopped again. | Runtime | Same mechanism as C-04; the quirk is declared in the database manifest |
| C-06 | An operation exceeds its deadline | No success is assumed; the Environment is blocked with `UNKNOWN_OUTCOME`. | Covered | `test_flow.test_operation_past_deadline_blocks_with_unknown_outcome` |
| C-07 | Extend after expiry or after an early Reclaim request | Rejected with `LEASE_EXPIRED`; the running Reclaim is not reverted. | Covered | `test_flow.test_extend_rejected_once_reclaim_started` |
| C-08 | Repeated request with the same `Idempotency-Key` | The original response is returned; a different body is rejected. | Covered | `test_flow.test_validation_and_idempotency` |

## Reclaim

| ID | Scenario | Required behavior | Status | Evidence |
|---|---|---|---|---|
| R-01 | Lease expires | The Environment is reclaimed, the final backup is kept when the data policy requires it, and Verify confirms removal before `RECLAIMED`. | Covered | `test_flow.test_expiry_reclaims_and_verifies` |
| R-02 | Resources remain after destroy | No terminal success; Verify retries, then blocks with `VERIFY_FAILED`. | Covered | `test_flow.test_verify_blocks_when_resources_remain` |
| R-03 | The inventory query fails during Verify | No terminal success; Verify is retried on the next pass. | Runtime | Exceptions in Verify do not mark the Environment reclaimed |
| R-04 | Verify scope | Verify checks tagged resources, Terraform state, DNS records and the final backup. | Partial | Only tagged resources are checked. |

## Cost

| ID | Scenario | Required behavior | Status | Evidence |
|---|---|---|---|---|
| K-01 | Compare always-on, stop-only and InfraFlow over the same period | Shown per Lease, including residual charges while asleep (EBS and RDS storage, snapshots). | Covered | `cost.py`; `test_flow.test_full_cycle` |
| K-02 | Hourly-billed resources | Billed per started hour; an idle environment is not put to sleep before the break-even time. | Covered | `test_desired.test_on_demand_idle_with_break_even` |
| K-03 | Unit prices | Estimates must be confirmed against the AWS Price List for the region. | Partial | Prices in `cost.py` are estimates for `ap-southeast-1`. |

## Registration of existing environments

| ID | Scenario | Status |
|---|---|---|
| X-01 | Register a compatible existing environment, with ownership and state handoff | Out of scope |
| X-02 | Reject an incompatible or unverifiable workspace without destruction | Out of scope |
| X-03 | Shared routes, certificates or DNS records not owned by the Environment | Out of scope |
