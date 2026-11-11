"""Controller: three trigger paths share one reconciliation function.

  mode=single  event path: the API has just written Desired State; reconcile one Environment now
  mode=all     periodic reconciliation (EventBridge, every 5 minutes)
  mode=sweep   orphan resource scanner (EventBridge, hourly); mark and report, never deletes
  mode=finish  the executor (Step Functions) reports the end of an operation

Reconciliation: Desired (desired.py) vs Actual (driver observe) -> planner -> model check -> lock -> executor.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from . import drivers
from .desired import desired_state, iso, manual_override, parse_ts
from .ics import checker, planner
from .ics.catalog import load_bundle
from .ics.compiler import DEFAULT_APP
from .ics.model import ABSENT, SNAPSHOTTED, ModelError, build_graph, make_state
from .store import LockError, get_store

OP_TIMEOUT = {"PROVISION": 30, "WAKE": 45, "SLEEP": 30, "RECLAIM": 75}  # minutes
VERIFY_MAX_ATTEMPTS = 4

_CATALOG = None
_NOW = None  # tests may pin the clock


def now() -> datetime:
    return _NOW or datetime.now(timezone.utc)


def catalog():
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = load_bundle()
    return _CATALOG


def new_operation_id() -> str:
    return "op_" + now().strftime("%Y%m%d%H%M%S") + "_" + secrets.token_hex(3)


def _sfn():
    return drivers.aws("stepfunctions")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def level_of(desired: str, env: dict) -> str:
    if desired == "AWAKE":
        return "awake"
    if desired == "RECLAIMED":
        return "reclaimed"
    if desired.startswith("ASLEEP:"):
        if env.get("status") == "REQUESTED":
            return "prepared"  # never woken: only the free resources exist
        return desired.split(":", 1)[1]
    raise ValueError(desired)


def action_of(level: str) -> str:
    return {"awake": "WAKE", "prepared": "PROVISION", "reclaimed": "RECLAIM"}.get(level, "SLEEP")


def actual_label(graph, sigma: dict, dns: str) -> str:
    if all(v in (ABSENT, SNAPSHOTTED) for v in sigma.values()):
        return "ABSENT"
    if sigma == graph.level_vector("awake") and dns == "APP":
        return "AWAKE"
    if sigma == graph.level_vector("prepared"):
        return "PREPARED"
    for lv in ("deep", "hibernate", "shallow"):
        if lv in graph.supported_levels and graph.satisfies_sleep(sigma, lv) and dns == "SLEEP":
            return f"ASLEEP:{lv}"
    return "MIXED"


def tf_base_vars(lease: dict, env: dict) -> dict:
    app = lease.get("app") or {}
    params = lease.get("parameters") or {}
    v = {
        "name_prefix": env["name_prefix"],
        "env_id": env["environment_id"],
        "size": params.get("size", "small"),
        "app_image": app.get("image", DEFAULT_APP["image"]),
        "app_port": int(app.get("port", DEFAULT_APP["port"])),
        "app_health_path": app.get("health_path", DEFAULT_APP["health_path"]),
    }
    if os.environ.get("CERTIFICATE_ARN"):
        v["certificate_arn"] = os.environ["CERTIFICATE_ARN"]
    return v


def attach_vars(graph, p: dict, lease: dict, env: dict) -> dict:
    """Each Terraform stage receives the full presence vector (not only the changes) plus the shared variables."""
    base = tf_base_vars(lease, env)
    snaps = env.get("snapshots") or {}
    for st in p["stages"]:
        tf = st.get("terraform")
        if not tf:
            continue
        vars_ = dict(base)
        for u, on in tf["presence"].items():
            vars_[f"{u}_present"] = bool(on)
        for u in graph.order:
            if graph.instances[u].is_data and snaps.get(u):
                vars_[f"{u}_restore_snapshot"] = snaps[u]
        tf["vars"] = vars_
    return p


def ctx_of(lease: dict, env: dict, op_id: str | None = None) -> dict:
    return {
        "operation_id": op_id,
        "environment_id": env["environment_id"],
        "name_prefix": env["name_prefix"],
        "host": env.get("host"),
        "lease_id": env["lease_id"],
        "org_id": env["org_id"],
        "blueprint": lease["blueprint_ref"],
        "tf_state_key": env.get("tf_state_key") or f"orgs/{env['org_id']}/envs/{env['environment_id']}/terraform.tfstate",
        "snapshots": env.get("snapshots") or {},
    }


# ---------------------------------------------------------------------------
# Reconcile one Environment
# ---------------------------------------------------------------------------

def reconcile(env_id: str, *, trigger_op: str | None = None, observe=None) -> dict:
    store = get_store()
    env = store.get_env(env_id)
    if env is None or env.get("status") == "RECLAIMED":
        return {"environment_id": env_id, "result": "skip"}
    lease = store.get_lease(env["lease_id"])
    t = now()

    # A workflow is running: let it finish. Past the deadline with the executor stopped -> UNKNOWN_OUTCOME.
    if env.get("active_operation_id"):
        return _check_stale(env, t)
    if env.get("blocked"):
        return {"environment_id": env_id, "result": "blocked"}

    if env.get("actual") == "AWAKE" and (lease.get("activity_policy") or {}).get("idle_timeout_minutes"):
        env = _update_activity(env, t)

    desired, source = desired_state(lease, env, t)
    graph = build_graph(catalog(), lease["blueprint_ref"])
    ctx = ctx_of(lease, env)
    sigma = (observe or drivers.observe_all)(graph, ctx)
    dns = env.get("dns", "SLEEP")
    label = actual_label(graph, sigma, dns)
    store.update_env(env_id, {"instances": sigma, "observed_at": iso(t), "actual": label,
                              "desired": desired, "desired_source": source})

    # Reclaim waiting for Verify
    if env.get("status") == "VERIFYING":
        return _verify(env, lease)

    level = level_of(desired, env)
    try:
        p = planner.plan(graph, sigma, level, dns,
                         keep_final_backup=bool((lease.get("data_policy") or {}).get("keep_final_backup", True)))
    except ModelError as e:
        return _block(env_id, "PLAN_UNSAFE", f"planner: {e}")

    if planner.is_noop(p):
        fields = {}
        if level == "prepared" and env.get("status") == "REQUESTED":
            fields["status"] = "PREPARED"
        if level == "reclaimed":
            fields["status"] = "VERIFYING"
            fields["verify_attempts"] = 0
        if fields:
            store.update_env(env_id, fields)
        if trigger_op:
            store.update_op(trigger_op, {"status": "SUCCEEDED", "finished_at": iso(t), "note": "already at target"})
        return {"environment_id": env_id, "result": "in_sync", "actual": label}

    start_state = make_state(graph, sigma, dns, health=(label == "AWAKE"))
    mc = checker.check_plan(graph, start_state, p, allow_unsafe_start=True)
    if not mc["passed"]:
        return _block(env_id, "PLAN_UNSAFE", json.dumps(mc["violation"], ensure_ascii=False)[:900])
    p["model_check"] = {"passed": True, "states_explored": mc["states_explored"],
                        "drift": mc.get("start_violations") or []}
    attach_vars(graph, p, lease, env)

    op_id = trigger_op or new_operation_id()
    try:
        store.acquire_lock(env_id, op_id)
    except LockError:
        if trigger_op:
            store.update_op(trigger_op, {"status": "FAILED", "finished_at": iso(t),
                                         "error": {"code": "CONCURRENT_OPERATION"}})
        return {"environment_id": env_id, "result": "locked"}

    op = store.get_op(op_id) or {"operation_id": op_id, "environment_id": env_id, "lease_id": env["lease_id"],
                                 "requested_at": iso(t), "source": source, "actor": "controller"}
    op.update({"action": action_of(level), "target_level": level, "status": "RUNNING", "plan": p,
               "reason": source, "started_at": iso(t)})
    store.put_op(op)
    ctx["operation_id"] = op_id
    ctx["allow_data_loss"] = bool(p.get("allow_data_loss"))
    _sfn().start_execution(stateMachineArn=os.environ["STATE_MACHINE_ARN"], name=op_id,
                           input=json.dumps({"ctx": ctx, "plan": p}, ensure_ascii=False))
    return {"environment_id": env_id, "result": "started", "operation_id": op_id, "action": op["action"]}


def _update_activity(env: dict, t: datetime) -> dict:
    """Primary activity signal: ALB RequestCount over the last 5 minutes."""
    try:
        lb = drivers._lb({"name_prefix": env["name_prefix"]})
        if lb is None:
            return env
        dim = lb["LoadBalancerArn"].split(":loadbalancer/", 1)[1]
        r = drivers.aws("cloudwatch").get_metric_statistics(
            Namespace="AWS/ApplicationELB", MetricName="RequestCount",
            Dimensions=[{"Name": "LoadBalancer", "Value": dim}],
            StartTime=t - timedelta(minutes=5), EndTime=t, Period=300, Statistics=["Sum"])
        if sum(dp["Sum"] for dp in r.get("Datapoints", [])) > 0:
            return get_store().update_env(env["environment_id"], {"last_activity_at": iso(t)})
    except Exception:
        pass  # missing datapoints count as zero requests (no update)
    return env


def _check_stale(env: dict, t: datetime) -> dict:
    store = get_store()
    op = store.get_op(env["active_operation_id"]) or {}
    started = parse_ts(op.get("started_at") or op.get("requested_at"))
    limit = OP_TIMEOUT.get(op.get("action"), 60)
    if started and t - started > timedelta(minutes=limit):
        running = False
        try:
            arn = os.environ["STATE_MACHINE_ARN"].replace(":stateMachine:", ":execution:") + ":" + op["operation_id"]
            running = _sfn().describe_execution(executionArn=arn)["status"] == "RUNNING"
        except Exception:  # treat an undeterminable status as not running
            running = False
        if not running:
            store.update_op(op["operation_id"], {"status": "BLOCKED", "error": {"code": "UNKNOWN_OUTCOME"},
                                                 "finished_at": iso(t)})
            store.release_lock(env["environment_id"], op["operation_id"])
            return _block(env["environment_id"], "UNKNOWN_OUTCOME", f"operation {op['operation_id']} exceeded its deadline")
    return {"environment_id": env["environment_id"], "result": "busy", "operation_id": env["active_operation_id"]}


def _block(env_id: str, code: str, detail: str) -> dict:
    get_store().update_env(env_id, {"blocked": True, "blocked_reason": {"code": code, "detail": detail, "at": iso(now())}})
    return {"environment_id": env_id, "result": "blocked", "code": code, "detail": detail}


# ---------------------------------------------------------------------------
# Operation completion (called by the executor)
# ---------------------------------------------------------------------------

def finish(event: dict) -> dict:
    store = get_store()
    op_id = event["operation_id"]
    op = store.get_op(op_id)
    env = store.get_env(op["environment_id"])
    lease = store.get_lease(env["lease_id"])
    t = now()
    status = event["status"]
    p = op["plan"]
    fields: dict = {}

    if status == "SUCCEEDED":
        level = op["target_level"]
        graph = build_graph(catalog(), lease["blueprint_ref"])
        before, after = p["from"], p["to"]
        for u in graph.order:
            if before.get(u) != after.get(u):
                store.append_state_log(env["environment_id"], iso(t), u, before.get(u), after.get(u), op_id)
        snaps = dict(env.get("snapshots") or {})
        snaps.update(op.get("snapshots") or {})
        fields.update({"instances": after, "snapshots": snaps, "observed_at": iso(t)})
        if level == "awake":
            fields.update({"actual": "AWAKE", "status": "ACTIVE", "awake_since": iso(t), "last_activity_at": iso(t)})
        elif level == "prepared":
            fields.update({"actual": "PREPARED", "status": "PREPARED"})
        elif level == "reclaimed":
            fields.update({"actual": "RECLAIMED", "status": "VERIFYING", "verify_attempts": 0})
        else:
            fields.update({"actual": f"ASLEEP:{level}", "status": "ACTIVE"})
            if op.get("reason") == "IDLE":
                fields["idle_slept_at"] = iso(t)
        store.update_op(op_id, {"status": "SUCCEEDED", "finished_at": iso(t)})
    elif status == "FAILED":
        # Health gate failed: the URL stays on the sleeping page and the Environment is put back to sleep
        fields["override"] = manual_override("ASLEEP:deep", t, lease.get("activity_policy"), source="HEALTH_FAILED")
        fields["override"]["until"] = iso(t + timedelta(hours=2))
        store.update_op(op_id, {"status": "FAILED", "finished_at": iso(t),
                                "error": {"code": "HEALTH_GATE_FAILED", "detail": _cause(event)}})
    else:
        code = "PLAN_UNSAFE" if "VALIDATION" in _cause(event).upper() or "PLAN_UNSAFE" in _cause(event) else "EXECUTION_FAILED"
        store.update_op(op_id, {"status": "BLOCKED", "finished_at": iso(t), "error": {"code": code, "detail": _cause(event)}})
        fields.update({"blocked": True, "blocked_reason": {"code": code, "detail": _cause(event), "at": iso(t),
                                                           "operation_id": op_id}})

    store.update_env(env["environment_id"], fields)
    store.release_lock(env["environment_id"], op_id)
    return {"operation_id": op_id, "status": status}


def _cause(event) -> str:
    err = event.get("error") or {}
    if isinstance(err, dict):
        return (str(err.get("Error", "")) + ": " + str(err.get("Cause", "")))[:1500]
    return str(err)[:1500]


# ---------------------------------------------------------------------------
# Verify after reclaim, and the orphan scanner
# ---------------------------------------------------------------------------

def tagged_resources(tag_filters: list) -> list:
    api = drivers.aws("resourcegroupstaggingapi")
    out, token = [], ""
    while True:
        r = api.get_resources(TagFilters=tag_filters, PaginationToken=token)
        out += r["ResourceTagMappingList"]
        token = r.get("PaginationToken") or ""
        if not token:
            return out


def _is_final_backup(res: dict) -> bool:
    tags = {t["Key"]: t["Value"] for t in res.get("Tags", [])}
    arn = res["ResourceARN"]
    is_snapshot = ":snapshot:" in arn or ":snapshot/" in arn  # RDS and EC2 snapshot ARNs
    return is_snapshot and tags.get("infraflow:purpose") in ("final-backup", "hibernate")


def _verify(env: dict, lease: dict) -> dict:
    store = get_store()
    left = [r["ResourceARN"] for r in tagged_resources([{"Key": "infraflow:env_id", "Values": [env["environment_id"]]}])
            if not _is_final_backup(r)]
    attempts = int(env.get("verify_attempts", 0)) + 1
    if not left:
        store.update_env(env["environment_id"], {"status": "RECLAIMED", "actual": "RECLAIMED", "verify_attempts": attempts,
                                                 "reclaimed_at": iso(now())})
        return {"environment_id": env["environment_id"], "result": "reclaimed"}
    if attempts >= VERIFY_MAX_ATTEMPTS:
        store.update_env(env["environment_id"], {"verify_attempts": attempts})
        return _block(env["environment_id"], "VERIFY_FAILED", "resources remain: " + ", ".join(left[:10]))
    store.update_env(env["environment_id"], {"verify_attempts": attempts})
    return {"environment_id": env["environment_id"], "result": "verifying", "left": left}


def sweep() -> dict:
    store = get_store()
    live = {e["environment_id"] for e in store.list_envs() if e.get("status") != "RECLAIMED"}
    found = []
    for r in tagged_resources([{"Key": "infraflow:managed", "Values": ["true"]}]):
        tags = {t["Key"]: t["Value"] for t in r.get("Tags", [])}
        env_id = tags.get("infraflow:env_id")
        if env_id in live or _is_final_backup(r):
            continue
        item = {"resource_arn": r["ResourceARN"], "env_id_tag": env_id or "-", "first_seen": iso(now()), "status": "OPEN"}
        store.put_orphan(item)
        found.append(item)
    return {"result": "swept", "orphans": len(found)}


# ---------------------------------------------------------------------------
# Lambda
# ---------------------------------------------------------------------------

def handler(event, context=None):
    mode = event.get("mode", "all")
    if mode == "finish":
        return finish(event)
    if mode == "single":
        return reconcile(event["environment_id"], trigger_op=event.get("operation_id"))
    if mode == "sweep":
        return sweep()
    results = []
    for env in get_store().list_envs():
        if env.get("status") == "RECLAIMED":
            continue
        try:
            results.append(reconcile(env["environment_id"]))
        except Exception as e:  # a failing Environment does not abort the pass for the others
            results.append({"environment_id": env["environment_id"], "result": "error", "error": str(e)[:300]})
    return {"mode": "all", "results": results}
