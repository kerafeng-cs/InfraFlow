"""Abstract model of a Blueprint.

- I: set of instances; E_p, E_s: `present` and `serving` edges, where (u, v) means u depends on v.
- System state s = (sigma, dns, health, snaps):
    sigma  : state of each instance, drawn from its billing class
    dns    : "SLEEP" (sleeping page) or "APP"
    health : True once the health gate has passed and nothing has changed since
    snaps  : data instances with an `available` snapshot taken in the current operation
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
    order: tuple  # instances in declaration order (for determinism)
    instances: dict  # name -> Instance
    present_edges: frozenset  # (u, v): u exists => v exists
    serving_edges: frozenset  # (u, v): u serves => v serves
    dns_target: str | None  # instance providing http.public to sys.dns
    supported_levels: tuple
    bindings: list = field(default_factory=list)

    # ---- graph ----
    def requires(self, u: str) -> set:
        return {v for (a, v) in self.present_edges | self.serving_edges if a == u}

    def depth(self) -> dict:
        memo: dict = {}

        def d(u: str, stack: tuple = ()) -> int:
            if u in stack:
                raise ModelError(f"cycle through {u}")
            if u not in memo:
                reqs = self.requires(u)
                memo[u] = 0 if not reqs else 1 + max(d(v, stack + (u,)) for v in reqs)
            return memo[u]

        return {u: d(u) for u in self.order}

    # ---- state vector per level ----
    def level_vector(self, level: str) -> dict:
        if level == "prepared":
            return {u: (PRESENT if self.instances[u].billing_class == "free" else ABSENT) for u in self.order}
        if level == "reclaimed":
            return {u: ABSENT for u in self.order}
        if level not in LEVELS:
            raise ModelError(f"invalid level: {level}")
        return {u: self.instances[u].levels[level] for u in self.order}

    def satisfies_sleep(self, sigma: dict, level: str) -> bool:
        """A sleep level is satisfied when every instance is in the level's state or in a cheaper one
        (for example PREPARED satisfies any ASLEEP state, and hibernate also satisfies deep)."""
        target = self.level_vector(level)
        for u in self.order:
            if sigma[u] == target[u]:
                continue
            if self.instances[u].billing_class != "free" and cheaper_or_equal_absent(sigma[u], target[u]):
                continue
            return False
        return True


# ---------------------------------------------------------------------------
# State and safety
# ---------------------------------------------------------------------------

def exists(state: str) -> bool:
    """SNAPSHOTTED means the resource has been deleted and only its snapshot remains."""
    return state not in (ABSENT, SNAPSHOTTED)


# Relative cost of each state, used to relax the target of sleep levels.
COST = {ABSENT: 0, SNAPSHOTTED: 0, STOPPED: 1, PRESENT: 2, RUNNING: 2}


def cheaper_or_equal_absent(cur: str, target: str) -> bool:
    """cur is cheaper than or equal to target, or neither exists (ABSENT/SNAPSHOTTED)."""
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
    """Returns the A1-A3 violations of a state. A4 is checked on transitions, see apply_action."""
    sigma = s.as_dict()
    out = []
    for (u, v) in sorted(graph.present_edges):
        if exists(sigma[u]) and not exists(sigma[v]):
            out.append(("A1", f"{u} exists but {v} does not"))
    for (u, v) in sorted(graph.serving_edges):
        iu, iv = graph.instances[u], graph.instances[v]
        if iu.serving(sigma[u]) and not iv.serving(sigma[v]):
            out.append(("A2", f"{u} is serving but {v} is not ({sigma[v]})"))
    if s.dns == APP:
        awake = graph.level_vector("awake")
        if not s.health:
            out.append(("A3", "DNS points to the application before the health gate has passed"))
        bad = [u for u in graph.order if sigma[u] != awake[u]]
        if bad:
            out.append(("A3", "DNS points to the application while " + ", ".join(bad) + " is not awake"))
    return out


# ---------------------------------------------------------------------------
# Atomic actions
# ---------------------------------------------------------------------------
# ("tf", inst, True|False)   Terraform creates or removes the instance (presence)
# ("start", inst) ("stop", inst)   driver
# ("snapshot", inst)          snapshot driver, waits until available
# ("dns", "SLEEP"|"APP")
# ("health",)                 health gate

def apply_action(graph: Graph, s: SysState, action: tuple, allow_data_loss: bool = False):
    """Returns (new state, transition violation or None).
    Raises ModelError when the action is not applicable, which indicates a malformed plan."""
    kind = action[0]
    sigma = s.as_dict()

    if kind == "dns":
        return SysState(s.sigma, action[1], s.health, s.snaps), None

    if kind == "health":
        awake = graph.level_vector("awake")
        if any(sigma[u] != awake[u] for u in graph.order):
            raise ModelError("health gate run before every instance is awake")
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
                return s.with_sigma(inst.name, RUNNING), None  # restored from snapshot
            raise ModelError(f"tf create {inst.name} while {cur}")
        if cur in (ABSENT, SNAPSHOTTED):
            raise ModelError(f"tf remove {inst.name} while {cur}")
        if inst.is_data:
            if inst.name in s.snaps:
                return s.with_sigma(inst.name, SNAPSHOTTED), None
            if allow_data_loss:
                return s.with_sigma(inst.name, ABSENT), None
            return s.with_sigma(inst.name, ABSENT), ("A4", f"deleting data instance {inst.name} without a snapshot")
        return s.with_sigma(inst.name, ABSENT), None

    if kind == "start":
        if cur != STOPPED:
            raise ModelError(f"start {inst.name} while {cur}")
        return s.with_sigma(inst.name, RUNNING), None

    if kind == "stop":
        if cur != RUNNING:
            raise ModelError(f"stop {inst.name} while {cur}")
        return s.with_sigma(inst.name, STOPPED), None

    if kind == "snapshot":
        if not inst.is_data or cur not in (RUNNING, STOPPED):
            raise ModelError(f"snapshot {inst.name} while {cur}")
        return SysState(s.sigma, s.dns, s.health, s.snaps | {inst.name}), None

    raise ModelError(f"unknown action: {action}")


# ---------------------------------------------------------------------------
# Build the graph from a blueprint and the catalog
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
            continue  # sys.lease_app is configuration, not an instance
        comp = catalog.component(bp["instances"][f_inst]["component"])
        req = next((r for r in comp.get("requires", []) if r["port"] == f_port), None)
        if req is None:
            continue  # reported separately by the composition checks
        when = req.get("when", "present")
        has_inputs = bool(req.get("inputs"))
        # Reading values (inputs) from the provider requires the provider to exist.
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
