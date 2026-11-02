"""Model checker (C7, C8, "luôn cứu được"): vét cạn mọi thứ tự xen kẽ của các hành động
song song trong từng giai đoạn của plan và kiểm mọi trạng thái đạt tới đều an toàn.

Không gian trạng thái nhỏ (web-db < 2.000 trạng thái), BFS chạy trong vài phần trăm giây.
"""

from __future__ import annotations

from collections import deque
from itertools import permutations

from . import planner
from .model import (APP, SLEEP, Graph, ModelError, SysState, apply_action, make_state, violations)


# ---------------------------------------------------------------------------
# Plan -> các nhóm hành động nguyên tử. Hành động trong cùng nhóm chạy song song (xen kẽ tùy ý);
# các nhóm chạy tuần tự.
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
    """BFS trên (chỉ số nhóm, tập hành động đã làm trong nhóm, trạng thái).

    allow_unsafe_start: dùng khi sửa trôi lệch (ví dụ ai đó bật EC2 trên console lúc môi trường ngủ).
    Khi đó trạng thái xuất phát đã vi phạm; plan được chấp nhận nếu không sinh vi phạm MỚI nào
    và kết thúc ở trạng thái an toàn.
    """
    groups = plan_groups(p)
    allow_loss = bool(p.get("allow_data_loss"))

    start_v = violations(graph, start)
    tolerated = set(start_v) if allow_unsafe_start else set()
    if start_v and not allow_unsafe_start:
        return {"passed": False, "states_explored": 1,
                "violation": {"rule": start_v[0][0], "message": "trạng thái xuất phát không an toàn: " + start_v[0][1],
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
                    "violation": {"rule": fv[0][0], "message": "kết thúc ở trạng thái không an toàn: " + fv[0][1],
                                  "trace": []}}
        if f.as_dict() != target:
            return {"passed": False, "states_explored": len(seen_states),
                    "violation": {"rule": "TARGET", "message": f"kết thúc ở {f.pretty()} thay vì {target}", "trace": []}}
        if p["target_level"] == "awake" and graph.dns_target and f.dns != APP:
            return {"passed": False, "states_explored": len(seen_states),
                    "violation": {"rule": "TARGET", "message": "thức xong nhưng DNS chưa trỏ vào ứng dụng", "trace": []}}

    return {"passed": True, "states_explored": len(seen_states), "reachable": seen_states,
            "start_violations": [list(x) for x in start_v]}


# ---------------------------------------------------------------------------
# Kiểm cả Blueprint: C7, C8, luôn cứu được
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

    # C7: mỗi mức hỗ trợ là trạng thái an toàn
    for lv in graph.supported_levels:
        v = violations(graph, level_state(graph, lv))
        add("C7", f"mức {lv} an toàn", not v, None if not v else {"rule": v[0][0], "message": v[0][1]})
    if not report["passed"]:
        return report

    # C8: mọi chuyển mức (kể cả từ prepared và tới reclaimed)
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
                add("C8", f"{a} -> {b}" + ("" if b != "reclaimed" else (" (giữ bản lưu cuối)" if keep else " (không lưu)")),
                    r["passed"], r.get("violation"))
                if r["passed"]:
                    reachable |= r["reachable"]

    # Luôn cứu được: từ mọi trạng thái đạt tới được (kể cả khi operation dừng giữa chừng)
    # planner luôn có đường an toàn về deep và về thu hồi.
    if recoverability and report["passed"]:
        rescue_level = "deep" if "deep" in graph.supported_levels else graph.supported_levels[-1]
        failed = None
        for s in sorted(reachable, key=lambda x: x.pretty()):
            clean = SysState(s.sigma, s.dns, s.health, frozenset())  # operation mới: chưa có snapshot
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
        add("RESCUE", f"luôn cứu được về {rescue_level} và reclaimed ({len(reachable)} trạng thái)", failed is None, failed)

    return report
