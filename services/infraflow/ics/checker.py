"""Model checker (C7, C8, RESCUE): explores every interleaving of the parallel actions in each
stage of a plan and verifies that every reachable state is safe.

The state space is small (web-db has fewer than 2,000 states), so breadth-first search finishes
in a few hundredths of a second.
"""

from __future__ import annotations

from collections import deque
from itertools import permutations

from . import planner
from .model import (APP, SLEEP, Graph, ModelError, SysState, apply_action, make_state, violations)


# ---------------------------------------------------------------------------
# Plan -> groups of atomic actions. Actions in a group run in parallel (any interleaving);
# groups run in sequence.
# ---------------------------------------------------------------------------

def _atomic(step: dict) -> tuple:
    a = step["action"]
    if a == "dns":
        return ("dns", step["value"])
    if a == "wait":
        return ("wait",)
    if a == "health":
        return ("health",)
    return (a, step["instance"])


def plan_groups(p: dict) -> list:
    groups = []
    for step in p["pre"]:
        groups.append([_atomic(step)])
    for st in p["stages"]:
        tf = st.get("terraform")
        if tf:
            groups.append([("tf", u, v) for u, v in sorted(tf["set"].items())])
        if st["drivers"]:
            groups.append([_atomic(d) for d in st["drivers"]])
    if p["health"]:
        groups.append([("health",)])
    for step in p["post"]:
        groups.append([_atomic(step)])
    return groups


def _describe(action: tuple) -> str:
    if action[0] == "tf":
        return f"terraform {action[1]}_present={'true' if action[2] else 'false'}"
    if action[0] == "dns":
        return f"dns -> {action[1]}"
    return " ".join(str(x) for x in action)


def check_plan(graph: Graph, start: SysState, p: dict, allow_unsafe_start: bool = False) -> dict:
    """Breadth-first search over (group index, actions done in the group, state).

    allow_unsafe_start: used to repair drift (for example an instance started from the console
    while the environment sleeps). The start state already violates a rule; the plan is accepted
    if it introduces no new violation and ends in a safe state.
    """
    groups = plan_groups(p)
    allow_loss = bool(p.get("allow_data_loss"))

    start_v = violations(graph, start)
    tolerated = set(start_v) if allow_unsafe_start else set()
    if start_v and not allow_unsafe_start:
        return {"passed": False, "states_explored": 1,
                "violation": {"rule": start_v[0][0], "message": "unsafe start state: " + start_v[0][1],
                              "trace": [start.pretty()]}}

    root = (0, frozenset(), start)
    parent = {root: None}
    queue = deque([root])
    seen_states = {start}
    finals = set()

    def trace(node, last_action=None, last_state=None):
        out = []
        while node is not None:
            out.append(node)
            node = parent[node][0] if parent[node] else None
        out.reverse()
        lines = [out[0][2].pretty()]
        for n in out[1:]:
            lines.append(f"  --{_describe(parent[n][1])}--> {n[2].pretty()}")
        if last_action is not None:
            lines.append(f"  --{_describe(last_action)}--> {last_state.pretty() if last_state else '?'}")
        return lines

    while queue:
        node = queue.popleft()
        gi, done, s = node
        if gi == len(groups):
            finals.add(s)
            continue
        group = groups[gi]
        remaining = [a for a in group if a not in done]
        if not remaining:
            nxt = (gi + 1, frozenset(), s)
            if nxt not in parent:
                parent[nxt] = (node, ("wait",))
                queue.append(nxt)
            continue
        for a in remaining:
            try:
                s2, tv = apply_action(graph, s, a, allow_data_loss=allow_loss)
            except ModelError as e:
                return {"passed": False, "states_explored": len(seen_states),
                        "violation": {"rule": "PLAN", "message": str(e), "trace": trace(node, a)}}
            if tv:
                return {"passed": False, "states_explored": len(seen_states),
                        "violation": {"rule": tv[0], "message": tv[1], "trace": trace(node, a, s2)}}
            v = [x for x in violations(graph, s2) if x not in tolerated]
            if v:
                return {"passed": False, "states_explored": len(seen_states),
                        "violation": {"rule": v[0][0], "message": v[0][1], "trace": trace(node, a, s2)}}
            seen_states.add(s2)
            nxt = (gi, done | {a}, s2)
            if nxt not in parent:
                parent[nxt] = (node, a)
                queue.append(nxt)

    target = p["to"]
    for f in finals:
        fv = violations(graph, f)
        if fv:
            return {"passed": False, "states_explored": len(seen_states),
                    "violation": {"rule": fv[0][0], "message": "ends in an unsafe state: " + fv[0][1],
                                  "trace": []}}
        if f.as_dict() != target:
            return {"passed": False, "states_explored": len(seen_states),
                    "violation": {"rule": "TARGET", "message": f"ends in {f.pretty()} instead of {target}", "trace": []}}
        if p["target_level"] == "awake" and graph.dns_target and f.dns != APP:
            return {"passed": False, "states_explored": len(seen_states),
                    "violation": {"rule": "TARGET", "message": "awake, but DNS does not point to the application", "trace": []}}

    return {"passed": True, "states_explored": len(seen_states), "reachable": seen_states,
            "start_violations": [list(x) for x in start_v]}


# ---------------------------------------------------------------------------
# Whole-Blueprint checks: C7, C8, RESCUE
# ---------------------------------------------------------------------------

def level_state(graph: Graph, level: str) -> SysState:
    awake = level == "awake"
    return make_state(graph, graph.level_vector(level), dns=APP if awake and graph.dns_target else SLEEP, health=awake)


def check_blueprint(graph: Graph, recoverability: bool = True) -> dict:
    report = {"blueprint": graph.blueprint, "passed": True, "checks": [], "states_explored": 0}

    def add(code, name, ok, detail=None):
        report["checks"].append({"code": code, "name": name, "passed": ok, "detail": detail})
        if not ok:
            report["passed"] = False

    # C7: every supported level is a safe state
    for lv in graph.supported_levels:
        v = violations(graph, level_state(graph, lv))
        add("C7", f"level {lv} is safe", not v, None if not v else {"rule": v[0][0], "message": v[0][1]})
    if not report["passed"]:
        return report

    # C8: every level transition, including from prepared and to reclaimed
    sources = ["prepared"] + list(graph.supported_levels)
    targets = list(graph.supported_levels) + ["reclaimed"]
    reachable = set()
    for a in sources:
        for b in targets:
            if a == b:
                continue
            start = make_state(graph, graph.level_vector(a)) if a == "prepared" else level_state(graph, a)
            for keep in ([True, False] if b == "reclaimed" else [True]):
                try:
                    p = planner.plan(graph, start.as_dict(), b, start.dns, keep_final_backup=keep)
                except ModelError as e:
                    add("C8", f"{a} -> {b}", False, {"rule": "PLAN", "message": str(e)})
                    continue
                r = check_plan(graph, start, p)
                report["states_explored"] += r["states_explored"]
                add("C8", f"{a} -> {b}" + ("" if b != "reclaimed" else (" (keep final backup)" if keep else " (no backup)")),
                    r["passed"], r.get("violation"))
                if r["passed"]:
                    reachable |= r["reachable"]

    # RESCUE: from every reachable state, including one where an operation stopped midway,
    # the planner has a safe path to deep and to reclaimed.
    if recoverability and report["passed"]:
        rescue_level = "deep" if "deep" in graph.supported_levels else graph.supported_levels[-1]
        failed = None
        for s in sorted(reachable, key=lambda x: x.pretty()):
            clean = SysState(s.sigma, s.dns, s.health, frozenset())  # a new operation starts without snapshots
            for lv in (rescue_level, "reclaimed"):
                try:
                    p = planner.plan(graph, clean.as_dict(), lv, clean.dns)
                    r = check_plan(graph, clean, p)
                except ModelError as e:
                    r = {"passed": False, "violation": {"rule": "PLAN", "message": str(e)}}
                if not r["passed"]:
                    failed = {"from": clean.pretty(), "to": lv, **r["violation"]}
                    break
            if failed:
                break
        add("RESCUE", f"recoverable to {rescue_level} and reclaimed ({len(reachable)} states)", failed is None, failed)

    return report
