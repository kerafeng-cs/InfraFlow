"""Mô hình trừu tượng của một Blueprint (TD mục 4.8, báo cáo mục 2.3.6).

- I: tập instance; E_p, E_s: cạnh `present` và `serving`, (u, v) nghĩa là u cần v.
- Trạng thái hệ thống s = (sigma, dns, health, snaps):
    sigma  : trạng thái từng instance theo lớp vòng đời
    dns    : "SLEEP" (sleeping page) hoặc "APP"
    health : True khi health gate đã đạt và chưa có gì thay đổi sau đó
    snaps  : instance dữ liệu đã có snapshot `available` trong operation hiện tại
"""

from __future__ import annotations

from dataclasses import dataclass, field

ABSENT = "ABSENT"
PRESENT = "PRESENT"
RUNNING = "RUNNING"
STOPPED = "STOPPED"
SNAPSHOTTED = "SNAPSHOTTED"

SLEEP = "SLEEP"
APP = "APP"

LEVELS = ("awake", "shallow", "deep", "hibernate")
SPECIAL_LEVELS = ("prepared", "reclaimed")


class ModelError(Exception):
    pass


@dataclass(frozen=True)
class Instance:
    name: str
    component: str
    billing_class: str
    data_class: str
    levels: dict
    serving_states: tuple
    drivers: dict  # action -> driver name

    @property
    def is_data(self) -> bool:
        return self.billing_class == "data"

    @property
    def initial_state(self) -> str:
        return PRESENT if self.billing_class in ("free", "hourly_no_data") else RUNNING

    def serving(self, state: str) -> bool:
        return state in self.serving_states


@dataclass
class Graph:
    blueprint: str
    order: tuple  # instance theo thứ tự khai báo (để tất định)
    instances: dict  # name -> Instance
    present_edges: frozenset  # (u, v): u tồn tại => v tồn tại
    serving_edges: frozenset  # (u, v): u phục vụ => v phục vụ
    dns_target: str | None  # instance cung cấp http.public cho sys.dns
    supported_levels: tuple
    bindings: list = field(default_factory=list)

    # ---- đồ thị ----
    def requires(self, u: str) -> set:
        return {v for (a, v) in self.present_edges | self.serving_edges if a == u}

    def depth(self) -> dict:
        memo: dict = {}

        def d(u: str, stack: tuple = ()) -> int:
            if u in stack:
                raise ModelError(f"chu trình qua {u}")
            if u not in memo:
                reqs = self.requires(u)
                memo[u] = 0 if not reqs else 1 + max(d(v, stack + (u,)) for v in reqs)
            return memo[u]

        return {u: d(u) for u in self.order}

    # ---- vector trạng thái theo mức ----
    def level_vector(self, level: str) -> dict:
        if level == "prepared":
            return {u: (PRESENT if self.instances[u].billing_class == "free" else ABSENT) for u in self.order}
        if level == "reclaimed":
            return {u: ABSENT for u in self.order}
        if level not in LEVELS:
            raise ModelError(f"mức không hợp lệ: {level}")
        return {u: self.instances[u].levels[level] for u in self.order}

    def satisfies_sleep(self, sigma: dict, level: str) -> bool:
        """Mức ngủ được thỏa khi mỗi instance đúng trạng thái của mức hoặc ở trạng thái rẻ hơn
        (ví dụ PREPARED thỏa mọi ASLEEP; đang hibernate thì cũng thỏa deep)."""
        target = self.level_vector(level)
        for u in self.order:
            if sigma[u] == target[u]:
                continue
            if self.instances[u].billing_class != "free" and cheaper_or_equal_absent(sigma[u], target[u]):
                continue
            return False
        return True


# ---------------------------------------------------------------------------
# Trạng thái và tính an toàn
# ---------------------------------------------------------------------------

def exists(state: str) -> bool:
    """SNAPSHOTTED nghĩa là tài nguyên đã bị xóa, chỉ còn snapshot."""
    return state not in (ABSENT, SNAPSHOTTED)


# Chi phí tương đối của trạng thái, dùng để nới đích của các mức ngủ.
COST = {ABSENT: 0, SNAPSHOTTED: 0, STOPPED: 1, PRESENT: 2, RUNNING: 2}


def cheaper_or_equal_absent(cur: str, target: str) -> bool:
    """cur rẻ hơn target, hoặc cả hai đều không tồn tại (ABSENT/SNAPSHOTTED)."""
    return COST[cur] < COST[target] or (not exists(cur) and not exists(target))


@dataclass(frozen=True)
class SysState:
    sigma: tuple  # tuple((name, state), ...) theo graph.order
    dns: str = SLEEP
    health: bool = False
    snaps: frozenset = frozenset()

    def as_dict(self) -> dict:
        return dict(self.sigma)

    def with_sigma(self, name: str, value: str) -> "SysState":
        d = dict(self.sigma)
        d[name] = value
        return SysState(tuple(d.items()), self.dns, False, self.snaps)

    def pretty(self) -> str:
        parts = [f"{k}={v}" for k, v in self.sigma]
        return "[" + ", ".join(parts) + f" | dns={self.dns} health={int(self.health)}]"


def make_state(graph: Graph, sigma: dict, dns: str = SLEEP, health: bool = False, snaps=()) -> SysState:
    return SysState(tuple((u, sigma[u]) for u in graph.order), dns, health, frozenset(snaps))


def violations(graph: Graph, s: SysState) -> list:
    """Trả về danh sách vi phạm A1-A3 (A4 kiểm ở bước chuyển, xem apply_action)."""
    sigma = s.as_dict()
    out = []
    for (u, v) in sorted(graph.present_edges):
        if exists(sigma[u]) and not exists(sigma[v]):
            out.append(("A1", f"{u} tồn tại nhưng {v} không tồn tại"))
    for (u, v) in sorted(graph.serving_edges):
        iu, iv = graph.instances[u], graph.instances[v]
        if iu.serving(sigma[u]) and not iv.serving(sigma[v]):
            out.append(("A2", f"{u} đang phục vụ nhưng {v} không phục vụ ({sigma[v]})"))
    if s.dns == APP:
        awake = graph.level_vector("awake")
        if not s.health:
            out.append(("A3", "DNS trỏ vào ứng dụng khi health gate chưa đạt"))
        bad = [u for u in graph.order if sigma[u] != awake[u]]
        if bad:
            out.append(("A3", "DNS trỏ vào ứng dụng khi " + ", ".join(bad) + " chưa ở trạng thái thức"))
    return out


# ---------------------------------------------------------------------------
# Hành động nguyên tử
# ---------------------------------------------------------------------------
# ("tf", inst, True|False)   Terraform bật/tắt instance (presence)
# ("start", inst) ("stop", inst)   driver
# ("snapshot", inst)          driver snapshot, chờ available
# ("dns", "SLEEP"|"APP")
# ("health",)                 health gate

def apply_action(graph: Graph, s: SysState, action: tuple, allow_data_loss: bool = False):
    """Trả về (trạng thái mới, vi phạm chuyển trạng thái hoặc None).
    Ném ModelError nếu hành động không áp dụng được (plan sai)."""
    kind = action[0]
    sigma = s.as_dict()

    if kind == "dns":
        return SysState(s.sigma, action[1], s.health, s.snaps), None

    if kind == "health":
        awake = graph.level_vector("awake")
        if any(sigma[u] != awake[u] for u in graph.order):
            raise ModelError("health gate chạy khi chưa mọi instance ở trạng thái thức")
        return SysState(s.sigma, s.dns, True, s.snaps), None

    if kind == "wait":
        return s, None

    inst = graph.instances[action[1]]
    cur = sigma[inst.name]

    if kind == "tf":
        present = action[2]
        if present:
            if cur == ABSENT:
                return s.with_sigma(inst.name, inst.initial_state), None
            if cur == SNAPSHOTTED:
                return s.with_sigma(inst.name, RUNNING), None  # khôi phục từ snapshot
            raise ModelError(f"tf bật {inst.name} khi đang {cur}")
        if cur in (ABSENT, SNAPSHOTTED):
            raise ModelError(f"tf tắt {inst.name} khi đang {cur}")
        if inst.is_data:
            if inst.name in s.snaps:
                return s.with_sigma(inst.name, SNAPSHOTTED), None
            if allow_data_loss:
                return s.with_sigma(inst.name, ABSENT), None
            return s.with_sigma(inst.name, ABSENT), ("A4", f"xóa {inst.name} (dữ liệu) khi chưa có snapshot")
        return s.with_sigma(inst.name, ABSENT), None

    if kind == "start":
        if cur != STOPPED:
            raise ModelError(f"start {inst.name} khi đang {cur}")
        return s.with_sigma(inst.name, RUNNING), None

    if kind == "stop":
        if cur != RUNNING:
            raise ModelError(f"stop {inst.name} khi đang {cur}")
        return s.with_sigma(inst.name, STOPPED), None

    if kind == "snapshot":
        if not inst.is_data or cur not in (RUNNING, STOPPED):
            raise ModelError(f"snapshot {inst.name} khi đang {cur}")
        return SysState(s.sigma, s.dns, s.health, s.snaps | {inst.name}), None

    raise ModelError(f"hành động lạ: {action}")


# ---------------------------------------------------------------------------
# Dựng đồ thị từ blueprint + catalog
# ---------------------------------------------------------------------------

def build_graph(catalog, blueprint_ref: str | None = None, blueprint: dict | None = None) -> Graph:
    bp = blueprint if blueprint is not None else catalog.blueprint(blueprint_ref)
    meta = bp["blueprint"]
    instances = {}
    order = []
    for name, spec in bp["instances"].items():
        comp = catalog.component(spec["component"])
        c = comp["component"]
        lc = comp.get("lifecycle", {})
        drivers = {k: v["driver"] for k, v in (lc.get("actions") or {}).items()}
        instances[name] = Instance(
            name=name,
            component=spec["component"],
            billing_class=c["billing_class"],
            data_class=c.get("data_class", "none"),
            levels=dict(lc.get("levels", {})),
            serving_states=tuple(lc.get("serving_states", [])),
            drivers=drivers,
        )
        order.append(name)

    present_edges, serving_edges = set(), set()
    dns_target = None
    for b in bp.get("bindings", []):
        f_inst, f_port = b["from"].split(".", 1)
        t_inst, _t_port = b["to"].split(".", 1)
        if f_inst == "sys":
            if f_port == "dns":
                dns_target = t_inst
            continue
        if t_inst == "sys":
            continue  # sys.lease_app: cấu hình, không phải instance
        comp = catalog.component(bp["instances"][f_inst]["component"])
        req = next((r for r in comp.get("requires", []) if r["port"] == f_port), None)
        if req is None:
            continue  # C-check báo lỗi riêng
        when = req.get("when", "present")
        has_inputs = bool(req.get("inputs"))
        # Lấy giá trị (inputs) từ phía cung cấp nghĩa là phía cung cấp phải tồn tại.
        if when == "present" or has_inputs:
            present_edges.add((f_inst, t_inst))
        if when == "serving":
            serving_edges.add((f_inst, t_inst))

    return Graph(
        blueprint=f"{meta['name']}@{meta['version']}",
        order=tuple(order),
        instances=instances,
        present_edges=frozenset(present_edges),
        serving_edges=frozenset(serving_edges),
        dns_target=dns_target,
        supported_levels=tuple(bp.get("supported_levels", ["awake", "deep"])),
        bindings=list(bp.get("bindings", [])),
    )
