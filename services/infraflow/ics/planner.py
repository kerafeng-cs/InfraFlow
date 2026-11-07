"""Generic planner: derives a lifecycle plan from the dependency graph.

Rules:
1. Split the changes into DOWN (stop serving or remove) and UP (create or start).
2. If DNS points to the application and the target is not `awake`, switch DNS to the sleeping
   page first and wait for connections to drain.
3. DOWN changes run first, by decreasing depth; UP changes run after, by increasing depth.
   Changes at the same depth share a stage.
4. Within a stage, all presence changes form one Terraform apply; drivers run in parallel.
5. A data resource is snapshotted, in a stage of its own, before it is removed.
6. When the target is `awake`, the health gate passes before DNS switches to the application.

A plan is handed to the executor only after it passes model checking (checker.check_plan).
"""

from __future__ import annotations

from .model import (ABSENT, APP, COST, cheaper_or_equal_absent, LEVELS, PRESENT, RUNNING, SLEEP, SNAPSHOTTED, STOPPED, Graph, ModelError,
                    exists, make_state, violations)

DRAIN_SECONDS = 90


def target_vector(graph: Graph, current: dict, level: str, keep_final_backup: bool = True) -> dict:
    """Concrete target vector of one level transition.

    - awake and prepared: exactly the level vector.
    - reclaimed: everything ABSENT; data resources become SNAPSHOTTED when a final backup is kept.
    - sleep levels: an instance that is already CHEAPER than its target stays as it is (it is not
      woken only to be put to sleep), provided the resulting vector is safe; otherwise the exact
      level vector is used.
    """
    base = graph.level_vector(level)
    if level in ("awake", "prepared"):
        return base
    if level == "reclaimed":
        out = {}
        for u in graph.order:
            inst = graph.instances[u]
            if inst.is_data and (current[u] == SNAPSHOTTED or (keep_final_backup and exists(current[u]))):
                out[u] = SNAPSHOTTED
            else:
                out[u] = ABSENT
        return out
    relaxed = {}
    for u in graph.order:
        inst = graph.instances[u]
        if inst.billing_class != "free" and cheaper_or_equal_absent(current[u], base[u]):
            relaxed[u] = current[u]
        else:
            relaxed[u] = base[u]
    if violations(graph, make_state(graph, relaxed)):
        return base
    return relaxed


def _driver(inst, action: str) -> str:
    name = inst.drivers.get(action)
    if not name:
        raise ModelError(f"{inst.name} has no driver for '{action}'")
    return name


def plan(graph: Graph, current: dict, level: str, dns_now: str = SLEEP,
         keep_final_backup: bool = True) -> dict:
    """Builds the lifecycle plan from `current` (instance -> state) to `level`.

    level: one of awake, shallow, deep, hibernate, prepared, reclaimed.
    keep_final_backup: used only when level is reclaimed (the data policy of the Lease).
    """
    if level not in LEVELS and level not in ("prepared", "reclaimed"):
        raise ModelError(f"invalid level: {level}")
    target = target_vector(graph, current, level, keep_final_backup)
    depth = graph.depth()
    reclaim = level == "reclaimed"

    down: dict = {}  # depth -> {"tf": {inst: False}, "drivers": [...], "snap": [...]}
    up: dict = {}

    def bucket(store, d):
        return store.setdefault(d, {"tf": {}, "drivers": [], "snap": []})

    for u in graph.order:
        inst = graph.instances[u]
        c, t = current[u], target[u]
        if c == t:
            continue
        d = depth[u]

        # ---- DOWN ----
        if t in (ABSENT, SNAPSHOTTED) and c not in (ABSENT, SNAPSHOTTED):
            b = bucket(down, d)
            if inst.is_data and (t == SNAPSHOTTED or (reclaim and keep_final_backup)):
                b["snap"].append({"instance": u, "action": "snapshot", "driver": _driver(inst, "snapshot")})
            b["tf"][u] = False
            continue
        if c == RUNNING and t == STOPPED:
            bucket(down, d)["drivers"].append({"instance": u, "action": "stop", "driver": _driver(inst, "stop")})
            continue

        # ---- UP ----
        if c in (ABSENT, SNAPSHOTTED) and t in (PRESENT, RUNNING):
            bucket(up, d)["tf"][u] = True
            continue
        if c == STOPPED and t == RUNNING:
            bucket(up, d)["drivers"].append({"instance": u, "action": "start", "driver": _driver(inst, "start")})
            continue

        raise ModelError(f"no transition for {u}: {c} -> {t}")

    presence = {u: current[u] not in (ABSENT, SNAPSHOTTED) for u in graph.order}
    restore = {u: current[u] == SNAPSHOTTED for u in graph.order}
    stages = []

    def emit(b: dict, name: str):
        if b["snap"]:
            stages.append({"name": f"{name}-snapshot", "terraform": None, "drivers": b["snap"]})
        tf = None
        if b["tf"]:
            presence.update(b["tf"])
            tf = {
                "mode": "apply",
                "set": dict(sorted(b["tf"].items())),
                "presence": dict(presence),
                "restore": sorted(u for u, v in b["tf"].items() if v and restore[u]),
                "allowed_instances": sorted(b["tf"]),
            }
        if tf or b["drivers"]:
            stages.append({"name": name, "terraform": tf, "drivers": b["drivers"]})

    for d in sorted(down, reverse=True):
        emit(down[d], f"down-{d}")
    for d in sorted(up):
        emit(up[d], f"up-{d}")

    if reclaim:
        # Reclaim: Terraform destroys the whole state, including anything the planner does not model.
        if stages and stages[-1]["terraform"]:
            stages[-1]["terraform"]["mode"] = "destroy"

    pre, health, post = [], [], []
    if dns_now == APP and level != "awake":
        pre = [{"action": "dns", "value": SLEEP, "driver": "dns.point"},
               {"action": "wait", "seconds": DRAIN_SECONDS, "driver": "wait.seconds"}]
    if level == "awake" and (stages or dns_now != APP):
        if graph.dns_target:
            inst = graph.instances[graph.dns_target]
            health = [{"instance": inst.name, "action": "health", "driver": "elbv2.target_healthy", "timeout_s": 900}]
        else:
            health = [{"action": "health", "driver": "wait.seconds", "seconds": 0}]
        if graph.dns_target:
            post = [{"action": "dns", "value": APP, "driver": "dns.point"}]

    return {
        "blueprint": graph.blueprint,
        "target_level": level,
        "from": dict(current),
        "to": dict(target),
        "pre": pre,
        "stages": stages,
        "health": health,
        "post": post,
        "allow_data_loss": reclaim and not keep_final_backup,
    }


def is_noop(p: dict) -> bool:
    return not (p["pre"] or p["stages"] or p["health"] or p["post"])
