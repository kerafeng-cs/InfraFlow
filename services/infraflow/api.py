"""Management API and public API. A Lambda behind an API Gateway HTTP API (payload format 2.0).

The API checks authorization, validates input, deduplicates requests, WRITES Desired State and
returns an operation_id. It never runs Terraform or changes infrastructure; that is the
controller's job.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from . import controller, cost, drivers
from .desired import DEFAULT_POLICY, iso, manual_override, parse_ts
from .ics import checker, static
from .ics.catalog import load_bundle
from .ics.compiler import DEFAULT_APP
from .ics.model import build_graph
from .store import LockError, VersionConflict, get_store

ADMIN_GROUP = "infraflow_admins"
LEASE_NAME = re.compile(r"^[a-z][a-z0-9]{1,15}$")
ENV_NAME = re.compile(r"^[a-z][a-z0-9]{0,7}$")
MAX_ENVS = 5


class ApiError(Exception):
    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def _now():
    return controller.now()


def _resp(status, body):
    return {"statusCode": status, "headers": {"content-type": "application/json"},
            "body": json.dumps(body, ensure_ascii=False, default=str)}


# ---------------------------------------------------------------------------
# Controller invocation (event path), asynchronous
# ---------------------------------------------------------------------------

def _invoke_controller(env_id, op_id):
    fn = os.environ.get("CONTROLLER_FUNCTION")
    if not fn:
        return
    drivers.aws("lambda").invoke(FunctionName=fn, InvocationType="Event",
                                 Payload=json.dumps({"mode": "single", "environment_id": env_id, "operation_id": op_id}))


INVOKE = _invoke_controller


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

def _principal(event):
    claims = ((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt", {}).get("claims") or {}
    groups = claims.get("cognito:groups") or ""
    if isinstance(groups, str):
        groups = [g.strip() for g in groups.strip("[]").replace(",", " ").split() if g.strip()]
    return {
        "sub": claims.get("sub", "anonymous"),
        "email": claims.get("email"),
        "org_id": claims.get("custom:org_id") or os.environ.get("DEFAULT_ORG_ID", "org_default"),
        "admin": ADMIN_GROUP in groups,
    }


def _own_lease(store, me, lease_id):
    lease = store.get_lease(lease_id)
    if lease is None or (lease["org_id"] != me["org_id"] and not me["admin"]):
        raise ApiError(404, "NOT_FOUND", "Lease does not exist")
    return lease


def _own_env(store, me, env_id):
    env = store.get_env(env_id)
    if env is None or (env["org_id"] != me["org_id"] and not me["admin"]):
        raise ApiError(404, "NOT_FOUND", "Environment does not exist")
    return env


# ---------------------------------------------------------------------------
# Request deduplication
# ---------------------------------------------------------------------------

def _idempotent(event, me, fn):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    key = headers.get("idempotency-key")
    if not key:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Missing Idempotency-Key header")
    store = get_store()
    scope = f"{me['org_id']}:{event['requestContext']['http']['method']}:{event['rawPath']}:{key}"
    digest = hashlib.sha256((event.get("body") or "").encode()).hexdigest()
    old = store.get_idem(scope)
    if old:
        if old["payload_sha256"] != digest:
            raise ApiError(422, "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key was already used with a different body")
        return old["status"], old["response"]
    status, body = fn()
    try:
        store.put_idem(scope, {"payload_sha256": digest, "status": status, "response": body,
                               "expires_at": int((_now() + timedelta(days=1)).timestamp())})
    except LockError:
        pass
    return status, body


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------

def _availability(env):
    if env.get("status") == "RECLAIMED":
        return "RECLAIMED"
    if env.get("blocked"):
        return "BLOCKED"
    if env.get("active_operation_id"):
        return "CHANGING"
    a = env.get("actual") or "REQUESTED"
    return a


def _env_view(env, detail=True):
    v = {k: env.get(k) for k in ("environment_id", "lease_id", "name", "host", "status", "actual", "desired",
                                 "desired_source", "override", "dns", "app_url", "blocked", "blocked_reason",
                                 "active_operation_id", "last_activity_at", "awake_since")}
    v["availability"] = _availability(env)
    if detail:
        v["instances"] = env.get("instances")
        v["observed_at"] = env.get("observed_at")
        v["snapshots"] = env.get("snapshots")
    v["url"] = _public_url(env)
    return v


def _public_url(env):
    domain = os.environ.get("DOMAIN")
    if domain:
        return f"https://{env['host']}.{domain}"
    site = os.environ.get("SITE_URL", "")
    return f"{site}/sleep.html?host={env['host']}"


def _op_view(op):
    if op is None:
        return None
    v = {k: op.get(k) for k in ("operation_id", "environment_id", "action", "target_level", "source", "status",
                                "requested_at", "started_at", "finished_at", "error", "snapshots")}
    p = op.get("plan")
    if p:
        v["plan"] = {"stages": [{"name": s["name"],
                                 "terraform": (s["terraform"] or {}).get("set"),
                                 "drivers": [f"{d['action']}:{d.get('instance', '')}" for d in s["drivers"]]}
                                for s in p["stages"]],
                     "health": bool(p.get("health")), "model_check": p.get("model_check")}
    return v


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def list_blueprints(event, me):
    cat = load_bundle()
    out = []
    for ref, bp in sorted(cat.blueprints.items()):
        g = build_graph(cat, ref)
        out.append({"ref": ref, "summary": bp["blueprint"].get("summary"), "parameters": bp.get("parameters"),
                    "instances": {u: {"component": g.instances[u].component, "billing_class": g.instances[u].billing_class}
                                  for u in g.order},
                    "supported_levels": list(g.supported_levels), "status": "CERTIFIED"})
    return 200, {"items": out}


def validate_blueprint(event, me):
    """Compose: static checks and model checking, synchronously (a few seconds); no dynamic verification."""
    cat = load_bundle()
    try:
        bp = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        raise ApiError(400, "INVALID_REQUEST", "body must be a blueprint in JSON")
    errs = static.check_composition(bp, cat)
    report = {"composition": errs, "passed": not errs}
    if not errs:
        rep = checker.check_blueprint(build_graph(cat, blueprint=bp))
        report.update({"passed": rep["passed"], "checks": rep["checks"], "states_explored": rep["states_explored"]})
    return 200, report


# ---------------------------------------------------------------------------
# Lease
# ---------------------------------------------------------------------------

def _validate_policy(pol):
    pol = {**DEFAULT_POLICY, **(pol or {})}
    if pol["mode"] not in ("schedule", "on_demand"):
        raise ApiError(400, "INVALID_REQUEST", "activity_policy.mode must be schedule or on_demand")
    if pol["mode"] == "on_demand" and not pol.get("idle_timeout_minutes"):
        raise ApiError(400, "INVALID_REQUEST", "on_demand requires idle_timeout_minutes")
    if pol["mode"] == "schedule":
        sch = pol.get("schedule") or {}
        if not re.match(r"^\d\d:\d\d$", sch.get("start", "")) or not re.match(r"^\d\d:\d\d$", sch.get("end", "")):
            raise ApiError(400, "INVALID_REQUEST", "schedule.start and schedule.end must be HH:MM")
    for k in ("off_hours_level", "idle_level"):
        if pol[k] not in ("deep", "hibernate"):
            raise ApiError(400, "INVALID_REQUEST", f"{k} must be deep or hibernate")
    if not 1 <= int(pol.get("manual_wake_hours", 2)) <= 8:
        raise ApiError(400, "INVALID_REQUEST", "manual_wake_hours must be in [1, 8]")
    return pol


def create_lease(event, me):
    def do():
        store = get_store()
        try:
            b = json.loads(event.get("body") or "{}")
        except json.JSONDecodeError:
            raise ApiError(400, "INVALID_REQUEST", "body is not JSON")
        name = b.get("name", "")
        if not LEASE_NAME.match(name):
            raise ApiError(400, "INVALID_REQUEST", "name: 2-16 lowercase letters or digits, starting with a letter")
        envs = b.get("environments") or []
        if not envs or len(envs) > MAX_ENVS or len(set(envs)) != len(envs) or not all(ENV_NAME.match(e) for e in envs):
            raise ApiError(400, "INVALID_REQUEST", f"environments: 1-{MAX_ENVS} distinct names of at most 8 lowercase letters or digits")
        cat = load_bundle()
        ref = b.get("blueprint_ref", "web-db@1.0.0")
        if ref not in cat.blueprints:
            raise ApiError(400, "BLUEPRINT_NOT_CERTIFIED", f"blueprint {ref} is not in the catalog")
        starts, expires = parse_ts(b.get("starts_at")) or _now(), parse_ts(b.get("expires_at"))
        if expires is None or expires <= starts:
            raise ApiError(400, "INVALID_REQUEST", "expires_at must be later than starts_at")
        if expires - starts > timedelta(days=120):
            raise ApiError(400, "ORG_LIMIT_EXCEEDED", "the maximum Lease duration is 120 days")
        size = (b.get("parameters") or {}).get("size", "small")
        if size not in ("small", "medium"):
            raise ApiError(400, "INVALID_REQUEST", "size must be small or medium")
        app = b.get("app") or {}
        app = {"image": app.get("image", DEFAULT_APP["image"]), "port": int(app.get("port", DEFAULT_APP["port"])),
               "health_path": app.get("health_path", DEFAULT_APP["health_path"])}
        if not app["health_path"].startswith("/") or not 1 <= app["port"] <= 65535:
            raise ApiError(400, "INVALID_REQUEST", "invalid app.port or app.health_path")
        dp = b.get("data_policy") or {}
        if "keep_final_backup" not in dp:
            raise ApiError(400, "INVALID_REQUEST", "data_policy.keep_final_backup must be set explicitly when creating a Lease")
        policy = _validate_policy(b.get("activity_policy"))
        for e in envs:
            if store.find_env_by_host(f"{name}-{e}"):
                raise ApiError(409, "NAME_TAKEN", f"{name}-{e} already exists")

        t = _now()
        lease_id = "ls_" + secrets.token_hex(5)
        lease = {"lease_id": lease_id, "org_id": me["org_id"], "name": name, "manager_id": me["sub"], "version": 1,
                 "blueprint_ref": ref, "parameters": {"size": size}, "app": app, "starts_at": iso(starts),
                 "expires_at": iso(expires), "activity_policy": policy,
                 "data_policy": {"keep_final_backup": bool(dp["keep_final_backup"]), "confirmed_by": me["sub"]},
                 "reclaim_requested": False, "created_at": iso(t)}
        store.put_lease(lease)
        ops = []
        for e in envs:
            env_id = f"{name}-{e}"
            store.put_env({"environment_id": env_id, "org_id": me["org_id"], "lease_id": lease_id, "name": e,
                           "host": env_id, "name_prefix": env_id, "origin": "create", "status": "REQUESTED",
                           "actual": "REQUESTED", "dns": "SLEEP", "blocked": False, "created_at": iso(t),
                           "capabilities": ["SLEEP", "WAKE", "RECLAIM"],
                           "tf_state_key": f"orgs/{me['org_id']}/envs/{env_id}/terraform.tfstate"})
            op_id = controller.new_operation_id()
            store.put_op({"operation_id": op_id, "environment_id": env_id, "lease_id": lease_id, "action": "PROVISION",
                          "status": "ACCEPTED", "source": "MANUAL", "actor": me["sub"], "requested_at": iso(t)})
            INVOKE(env_id, op_id)
            ops.append({"environment_id": env_id, "operation_id": op_id})
        return 202, {"lease_id": lease_id, "operations": ops}

    return _idempotent(event, me, do)


def list_leases(event, me):
    store = get_store()
    items = []
    for l in sorted(store.list_leases(me["org_id"]), key=lambda x: x["created_at"], reverse=True):
        envs = store.list_envs(l["lease_id"])
        items.append({"lease_id": l["lease_id"], "name": l["name"], "blueprint_ref": l["blueprint_ref"],
                      "starts_at": l["starts_at"], "expires_at": l["expires_at"],
                      "mode": (l.get("activity_policy") or {}).get("mode"),
                      "environments": [{"name": e["name"], "availability": _availability(e)} for e in envs]})
    return 200, {"items": items}


def get_lease(event, me, lease_id):
    store = get_store()
    l = _own_lease(store, me, lease_id)
    envs = [_env_view(e, detail=True) for e in sorted(store.list_envs(lease_id), key=lambda x: x["name"])]
    return 200, {**l, "environments": envs}


def extend_lease(event, me, lease_id):
    def do():
        store = get_store()
        l = _own_lease(store, me, lease_id)
        if l.get("reclaim_requested") or parse_ts(l["expires_at"]) <= _now():
            raise ApiError(409, "LEASE_EXPIRED", "Lease has expired or is being reclaimed; it can no longer be extended")
        b = json.loads(event.get("body") or "{}")
        exp = parse_ts(b.get("expires_at"))
        if exp is None or exp <= parse_ts(l["expires_at"]):
            raise ApiError(400, "INVALID_REQUEST", "the new expires_at must be later than the current one")
        try:
            l2 = store.update_lease(lease_id, {"expires_at": iso(exp)}, expected_version=b.get("version"))
        except VersionConflict:
            raise ApiError(409, "VERSION_CONFLICT", "Lease was modified; reload and retry")
        return 200, {"lease_id": lease_id, "expires_at": l2["expires_at"], "version": l2["version"]}

    return _idempotent(event, me, do)


def put_activity_policy(event, me, lease_id):
    store = get_store()
    l = _own_lease(store, me, lease_id)
    b = json.loads(event.get("body") or "{}")
    pol = _validate_policy(b.get("activity_policy"))
    try:
        l2 = store.update_lease(lease_id, {"activity_policy": pol}, expected_version=b.get("version"))
    except VersionConflict:
        raise ApiError(409, "VERSION_CONFLICT", "Lease was modified; reload and retry")
    # Enabling idle sleep grants a grace period instead of sleeping immediately
    if pol.get("idle_timeout_minutes"):
        for e in store.list_envs(lease_id):
            store.update_env(e["environment_id"], {"last_activity_at": iso(_now())})
    return 200, {"lease_id": lease_id, "activity_policy": l2["activity_policy"], "version": l2["version"]}


def reclaim_lease(event, me, lease_id):
    def do():
        store = get_store()
        _own_lease(store, me, lease_id)
        b = json.loads(event.get("body") or "{}")
        if b.get("confirm") is not True:
            raise ApiError(400, "CONFIRMATION_REQUIRED", "early reclaim requires confirm = true")
        store.update_lease(lease_id, {"reclaim_requested": True})
        ops = []
        for e in store.list_envs(lease_id):
            op_id = controller.new_operation_id()
            store.put_op({"operation_id": op_id, "environment_id": e["environment_id"], "lease_id": lease_id,
                          "action": "RECLAIM", "status": "ACCEPTED", "source": "MANUAL", "actor": me["sub"],
                          "requested_at": iso(_now())})
            INVOKE(e["environment_id"], op_id)
            ops.append({"environment_id": e["environment_id"], "operation_id": op_id})
        return 202, {"lease_id": lease_id, "operations": ops}

    return _idempotent(event, me, do)


def lease_cost(event, me, lease_id):
    store = get_store()
    l = _own_lease(store, me, lease_id)
    q = event.get("queryStringParameters") or {}
    start = parse_ts(q.get("from")) or parse_ts(l["created_at"])
    end = parse_ts(q.get("to")) or min(_now(), parse_ts(l["expires_at"]))
    size = (l.get("parameters") or {}).get("size", "small")
    per_env = {}
    totals = {"always_on": 0.0, "stop_only": 0.0, "infraflow": 0.0}
    for e in store.list_envs(lease_id):
        r = cost.scenarios(store.list_state_log(e["environment_id"]), start, end, size, l.get("activity_policy"))
        per_env[e["name"]] = r
        for k in totals:
            totals[k] = round(totals[k] + r[k], 4)
    return 200, {"from": iso(start), "to": iso(end), "currency": "USD", "estimate": True,
                 "totals": totals, "environments": per_env}


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

def get_env(event, me, env_id):
    store = get_store()
    return 200, _env_view(_own_env(store, me, env_id))


def _request_state(env, lease, value, me, source):
    """Manual action: writes an override with an expiry; conflicts are resolved against the active operation."""
    store = get_store()
    t = _now()
    if lease.get("reclaim_requested") or parse_ts(lease["expires_at"]) <= t:
        raise ApiError(409, "LEASE_EXPIRED", "Lease has expired or is being reclaimed")
    if env.get("blocked"):
        raise ApiError(409, "ENVIRONMENT_BLOCKED", "Environment is BLOCKED and requires an administrator")
    if env.get("status") in ("RECLAIMED", "VERIFYING"):
        raise ApiError(409, "LEASE_EXPIRED", "Environment has been reclaimed")
    active = env.get("active_operation_id")
    want_awake = value == "AWAKE"
    if active:
        op = store.get_op(active) or {}
        if (op.get("target_level") == "awake") == want_awake:
            return 202, {"operation_id": active, "status": op.get("status"), "existing": True}
        raise ApiError(409, "CONCURRENT_OPERATION", "an operation with the opposite target is running; wait for it to finish",
                       {"operation_id": active})
    ov = manual_override(value, t, lease.get("activity_policy"), source=source)
    store.update_env(env["environment_id"], {"override": ov, "last_activity_at": iso(t)})
    op_id = controller.new_operation_id()
    store.put_op({"operation_id": op_id, "environment_id": env["environment_id"], "lease_id": env["lease_id"],
                  "action": "WAKE" if want_awake else "SLEEP", "status": "ACCEPTED", "source": source,
                  "actor": me["sub"], "requested_at": iso(t)})
    INVOKE(env["environment_id"], op_id)
    return 202, {"operation_id": op_id, "status": "ACCEPTED", "override": ov}


def wake_env(event, me, env_id):
    def do():
        store = get_store()
        env = _own_env(store, me, env_id)
        return _request_state(env, store.get_lease(env["lease_id"]), "AWAKE", me, "MANUAL")

    return _idempotent(event, me, do)


def sleep_env(event, me, env_id):
    def do():
        store = get_store()
        env = _own_env(store, me, env_id)
        lease = store.get_lease(env["lease_id"])
        b = json.loads(event.get("body") or "{}")
        level = b.get("level") or (lease.get("activity_policy") or {}).get("off_hours_level", "deep")
        if level not in ("deep", "hibernate"):
            raise ApiError(400, "INVALID_REQUEST", "level must be deep or hibernate")
        return _request_state(env, lease, f"ASLEEP:{level}", me, "MANUAL")

    return _idempotent(event, me, do)


def heartbeat(event, me, env_id):
    store = get_store()
    _own_env(store, me, env_id)
    store.update_env(env_id, {"last_activity_at": iso(_now())})
    return 204, None


def env_operations(event, me, env_id):
    store = get_store()
    _own_env(store, me, env_id)
    return 200, {"items": [_op_view(o) for o in store.list_ops(env_id)]}


def get_operation(event, me, op_id):
    store = get_store()
    op = store.get_op(op_id)
    if op is None:
        raise ApiError(404, "NOT_FOUND", "operation does not exist")
    _own_env(store, me, op["environment_id"])
    return 200, _op_view(op)


# ---------------------------------------------------------------------------
# Public API for the sleeping page: exposes no resource IDs, error details or operation IDs
# ---------------------------------------------------------------------------

STEP_LABELS = {"up-0": "Creating the network", "up-1": "Creating Internet egress and starting the database",
               "up-2": "Starting the application", "up-3": "Creating the entry point",
               "health": "Checking the application"}


def _public_env(host):
    store = get_store()
    env = store.find_env_by_host(host or "")
    if env is None:
        raise ApiError(404, "NOT_FOUND", "Environment does not exist or has expired")
    lease = store.get_lease(env["lease_id"])
    if env.get("status") == "RECLAIMED":
        raise ApiError(404, "NOT_FOUND", "Environment does not exist or has expired")
    return store, env, lease


def public_status(event, me):
    q = event.get("queryStringParameters") or {}
    store, env, lease = _public_env(q.get("host"))
    t = _now()
    avail = _availability(env)
    if avail == "CHANGING":
        op = store.get_op(env["active_operation_id"]) or {}
        avail = "WAKING" if op.get("target_level") == "awake" else "SLEEPING"
    can_wake = (not env.get("blocked") and parse_ts(lease["expires_at"]) > t and not lease.get("reclaim_requested")
                and avail not in ("AWAKE", "WAKING"))
    progress = None
    if avail == "WAKING":
        op = store.get_op(env["active_operation_id"]) or {}
        stages = [s["name"] for s in (op.get("plan") or {}).get("stages", [])]
        progress = {"stages": [STEP_LABELS.get(s, s) for s in stages] + ["Checking the application"]}
    return 200, {"environment_name": env["name"], "lease_name": lease["name"], "availability": avail,
                 "can_wake": can_wake, "app_url": env.get("app_url") if avail == "AWAKE" else None,
                 "progress": progress, "expires_at": lease["expires_at"]}


def public_wake(event, me):
    b = json.loads(event.get("body") or "{}")
    store, env, lease = _public_env(b.get("host"))
    t = _now()
    last = parse_ts(env.get("public_wake_at"))
    if last and t - last < timedelta(seconds=30):
        raise ApiError(429, "RATE_LIMITED", "Please wait a moment and try again")
    store.update_env(env["environment_id"], {"public_wake_at": iso(t)})
    status, body = _request_state(env, lease, "AWAKE", {"sub": "public-url"}, "PUBLIC_URL")
    return 202, {"accepted": True}


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

def _admin(me):
    if not me["admin"]:
        raise ApiError(403, "FORBIDDEN", "administrators only")


def admin_blocked(event, me):
    _admin(me)
    return 200, {"items": [_env_view(e) for e in get_store().list_envs() if e.get("blocked")]}


def admin_resolve(event, me, env_id):
    _admin(me)
    store = get_store()
    b = json.loads(event.get("body") or "{}")
    if b.get("action") not in ("retry", "mark_resolved", "force_cleanup"):
        raise ApiError(400, "INVALID_REQUEST", "action: retry | mark_resolved | force_cleanup")
    if not b.get("note"):
        raise ApiError(400, "INVALID_REQUEST", "note is required")
    env = store.get_env(env_id)
    fields = {"blocked": False, "resolved": {"by": me["sub"], "action": b["action"], "note": b["note"], "at": iso(_now())}}
    remove = ["blocked_reason"]
    if b["action"] == "force_cleanup":
        lease = store.get_lease(env["lease_id"])
        store.update_lease(env["lease_id"], {"reclaim_requested": True,
                                             "data_policy": {**(lease.get("data_policy") or {}), "keep_final_backup": False}})
    store.update_env(env_id, fields, remove=remove)
    INVOKE(env_id, None)
    return 200, {"environment_id": env_id, "resolved": b["action"]}


def admin_orphans(event, me):
    _admin(me)
    return 200, {"items": get_store().list_orphans()}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

ROUTES = [
    ("GET", r"/v1/catalog/blueprints", list_blueprints, True),
    ("POST", r"/v1/blueprints/validate", validate_blueprint, True),
    ("POST", r"/v1/leases", create_lease, True),
    ("GET", r"/v1/leases", list_leases, True),
    ("GET", r"/v1/leases/([^/]+)", get_lease, True),
    ("POST", r"/v1/leases/([^/]+)/extend", extend_lease, True),
    ("PUT", r"/v1/leases/([^/]+)/activity-policy", put_activity_policy, True),
    ("POST", r"/v1/leases/([^/]+)/reclaim", reclaim_lease, True),
    ("GET", r"/v1/leases/([^/]+)/cost", lease_cost, True),
    ("GET", r"/v1/environments/([^/]+)", get_env, True),
    ("POST", r"/v1/environments/([^/]+)/wake", wake_env, True),
    ("POST", r"/v1/environments/([^/]+)/sleep", sleep_env, True),
    ("POST", r"/v1/environments/([^/]+)/heartbeat", heartbeat, True),
    ("GET", r"/v1/environments/([^/]+)/operations", env_operations, True),
    ("GET", r"/v1/operations/([^/]+)", get_operation, True),
    ("GET", r"/v1/public/status", public_status, False),
    ("POST", r"/v1/public/wake", public_wake, False),
    ("GET", r"/v1/admin/blocked", admin_blocked, True),
    ("POST", r"/v1/admin/environments/([^/]+)/resolve", admin_resolve, True),
    ("GET", r"/v1/admin/orphans", admin_orphans, True),
]


def handler(event, context=None):
    method = event["requestContext"]["http"]["method"]
    path = event.get("rawPath", "/")
    if method == "OPTIONS":
        return _resp(204, None)
    try:
        for m, pattern, fn, auth in ROUTES:
            if m != method:
                continue
            match = re.fullmatch(pattern, path)
            if match:
                me = _principal(event) if auth else {"sub": "public", "org_id": None, "admin": False}
                status, body = fn(event, me, *match.groups())
                return _resp(status, body)
        raise ApiError(404, "NOT_FOUND", f"no route for {method} {path}")
    except ApiError as e:
        return _resp(e.status, {"error": {"code": e.code, "message": e.message, "details": e.details}})
    except json.JSONDecodeError:
        return _resp(400, {"error": {"code": "INVALID_REQUEST", "message": "body is not JSON"}})
