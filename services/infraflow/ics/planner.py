"""Planner tổng quát: sinh lifecycle plan từ đồ thị phụ thuộc (TD mục 8.1, báo cáo mục 2.3.5).

Quy tắc:
1. Chia thay đổi thành XUỐNG (giảm phục vụ / xóa) và LÊN (tạo / khởi động).
2. Đang trỏ DNS vào ứng dụng mà đích không phải `awake`: đổi DNS về sleeping page trước, chờ drain.
3. XUỐNG trước theo độ sâu giảm dần; LÊN sau theo độ sâu tăng dần. Cùng độ sâu thì chung giai đoạn.
4. Trong một giai đoạn: mọi thay đổi presence gộp thành một lần Terraform apply; driver chạy song song.
5. Trước khi tắt tài nguyên dữ liệu: snapshot (giai đoạn riêng, trước đó).
6. Đích là `awake`: health gate rồi mới đổi DNS vào ứng dụng.

Plan chỉ được giao cho executor sau khi qua model checking (checker.check_plan).
"""

from __future__ import annotations

from .model import (ABSENT, APP, COST, cheaper_or_equal_absent, LEVELS, PRESENT, RUNNING, SLEEP, SNAPSHOTTED, STOPPED, Graph, ModelError,
                    exists, make_state, violations)

DRAIN_SECONDS = 90


def target_vector(graph: Graph, current: dict, level: str, keep_final_backup: bool = True) -> dict:
    """Đích cụ thể của một lần chuyển mức.

    - awake / prepared: đúng tuyệt đối vector của mức.
    - reclaimed: mọi thứ ABSENT; tài nguyên dữ liệu thành SNAPSHOTTED nếu giữ bản lưu cuối.
    - các mức ngủ: instance nào đang RẺ HƠN đích thì giữ nguyên (không đánh thức chỉ để cho ngủ),
      miễn là vector thu được vẫn an toàn; không thì dùng đúng vector của mức.
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
        raise ModelError(f"{inst.name} không có driver cho '{action}'")
    return name


def plan(graph: Graph, current: dict, level: str, dns_now: str = SLEEP,
         keep_final_backup: bool = True) -> dict:
    """Sinh lifecycle plan từ `current` (dict instance -> trạng thái) tới `level`.

    level: một trong awake/shallow/deep/hibernate/prepared/reclaimed.
    keep_final_backup: chỉ dùng khi level = reclaimed (chính sách dữ liệu của Lease).
    """
    if level not in LEVELS and level not in ("prepared", "reclaimed"):
        raise ModelError(f"mức không hợp lệ: {level}")
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

        # ---- XUỐNG ----
        if t in (ABSENT, SNAPSHOTTED) and c not in (ABSENT, SNAPSHOTTED):
            b = bucket(down, d)
            if inst.is_data and (t == SNAPSHOTTED or (reclaim and keep_final_backup)):
                b["snap"].append({"instance": u, "action": "snapshot", "driver": _driver(inst, "snapshot")})
            b["tf"][u] = False
            continue
        if c == RUNNING and t == STOPPED:
            bucket(down, d)["drivers"].append({"instance": u, "action": "stop", "driver": _driver(inst, "stop")})
            continue

        # ---- LÊN ----
        if c in (ABSENT, SNAPSHOTTED) and t in (PRESENT, RUNNING):
            bucket(up, d)["tf"][u] = True
            continue
        if c == STOPPED and t == RUNNING:
            bucket(up, d)["drivers"].append({"instance": u, "action": "start", "driver": _driver(inst, "start")})
            continue

        raise ModelError(f"không có đường chuyển {u}: {c} -> {t}")

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
        # Thu hồi: Terraform destroy toàn bộ state (bao gồm cả những gì planner không biết).
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
