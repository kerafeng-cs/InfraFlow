"""Static component checks (S1, S4-S7, F) and Blueprint composition checks (C1-C6).

S2 and S8 require running Terraform and belong to dynamic verification; this module covers
only the checks that need no cloud resources.
"""

from __future__ import annotations

import re
from pathlib import Path

REQUIRED_COMPONENT_KEYS = ("name", "version", "owner", "billing_class", "data_class", "resource_types")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
NAME = re.compile(r"^[a-z][a-z0-9-]{2,40}$")
LEVEL_NAMES = ("awake", "shallow", "deep", "hibernate")

FORBIDDEN = [
    (re.compile(r"\bprovisioner\s+\""), "provisioner"),
    (re.compile(r"\bdata\s+\"external\""), 'data "external"'),
    (re.compile(r"\bdata\s+\"http\""), 'data "http"'),
    (re.compile(r"\bresource\s+\"local_file\""), "local_file"),
    (re.compile(r"\bbackend\s+\"[a-z0-9_]+\""), "backend"),
    (re.compile(r"^\s*cloud\s*\{", re.M), "cloud"),
    (re.compile(r"\bprovider\s+\"[a-z0-9_]+\"\s*\{"), "provider block declared inside a component"),
    (re.compile(r"source\s*=\s*\"(git::|github\.com|https?://)"), "external module source that is not vendored"),
    (re.compile(r"ignore_changes\s*=\s*all"), "ignore_changes = all"),
]
RESOURCE_DECL = re.compile(r'^\s*resource\s+"([a-z0-9_]+)"\s+"[A-Za-z0-9_-]+"', re.M)


def _err(out, code, msg):
    out.append({"code": code, "message": msg})


def check_component(manifest: dict, registry: dict, tf_dir: str | Path | None = None) -> list:
    out: list = []
    c = manifest.get("component") or {}

    # S1: schema
    for k in REQUIRED_COMPONENT_KEYS:
        if k not in c:
            _err(out, "S1", f"missing component.{k}")
    if out:
        return out
    if not NAME.match(c["name"]):
        _err(out, "S1", f"invalid name: {c['name']}")
    if not SEMVER.match(str(c["version"])):
        _err(out, "S1", f"version is not semver: {c['version']}")

    classes = registry["classes"]
    rtypes = registry["resource_types"]
    bclass = c["billing_class"]
    if bclass not in classes:
        _err(out, "S1", f"unknown billing_class: {bclass}")
        return out

    # S5: the declared billing class matches the Resource Type Registry
    for rt in c["resource_types"]:
        if rt not in rtypes:
            _err(out, "S5", f"resource type not in the Resource Type Registry: {rt}")
            continue
        forced = rtypes[rt].get("class")
        if forced and forced != "free" and forced != bclass:
            # A resource whose type forces a billing class, declared with a different class
            rank = {"free": 0, "stoppable": 1, "hourly_no_data": 2, "data": 3}
            if rank[forced] > rank[bclass] or forced == "data":
                _err(out, "S5", f"{rt} is class {forced} but the component declares {bclass}")
        if rtypes[rt].get("data") and c.get("data_class") == "none":
            _err(out, "S5", f"{rt} holds data but data_class is none")

    # S6: lifecycle matches the billing class
    lc = manifest.get("lifecycle") or {}
    valid_states = set(classes[bclass]["states"])
    levels = lc.get("levels") or {}
    for lv in ("awake", "deep"):
        if lv not in levels:
            _err(out, "S6", f"missing level {lv}")
    for lv, st in levels.items():
        if lv not in LEVEL_NAMES:
            _err(out, "S6", f"unknown level: {lv}")
        if st not in valid_states:
            _err(out, "S6", f"level {lv} uses state {st}, which is not valid for class {bclass}")
    serving = lc.get("serving_states") or []
    if levels.get("awake") not in serving:
        _err(out, "S6", "the state of level awake must be one of serving_states")
    actions = {k: v.get("driver") for k, v in (lc.get("actions") or {}).items()}
    used = set(levels.values())
    if bclass in ("stoppable", "data") and "STOPPED" in used:
        for a in ("start", "stop"):
            if a not in actions:
                _err(out, "S6", f"class {bclass} uses STOPPED and therefore requires driver '{a}'")
    if "SNAPSHOTTED" in used:
        if "snapshot" not in actions:
            _err(out, "S6", "uses SNAPSHOTTED and therefore requires driver 'snapshot'")
        if not lc.get("restore_variable"):
            _err(out, "S6", "uses SNAPSHOTTED and therefore requires restore_variable")
    for a, d in actions.items():
        if d not in registry["drivers"]:
            _err(out, "S6", f"driver not in the Driver Registry: {d}")

    # S7: ports have known types and existing attributes
    ptypes = registry["port_types"]
    for p in manifest.get("provides") or []:
        if p["type"] not in ptypes:
            _err(out, "S7", f"unknown port type: {p['type']}")
            continue
        for attr in (p.get("attributes") or {}):
            if attr not in ptypes[p["type"]]:
                _err(out, "S7", f"port {p['port']}: attribute {attr} is not part of {p['type']}")
    for r in manifest.get("requires") or []:
        if r["type"] not in ptypes:
            _err(out, "S7", f"unknown port type: {r['type']}")
            continue
        if r.get("when", "present") not in ("present", "serving"):
            _err(out, "S7", f"port {r['port']}: when must be present or serving")
        for attr in (r.get("inputs") or {}):
            if attr not in ptypes[r["type"]]:
                _err(out, "S7", f"port {r['port']}: attribute {attr} is not part of {r['type']}")
    outputs = manifest.get("outputs") or {}
    for a, spec in (lc.get("actions") or {}).items():
        tgt = spec.get("target")
        if tgt and outputs and not outputs.get(tgt, {}).get("stable"):
            _err(out, "S7", f"target of action {a} ({tgt}) must be a stable output")

    # S4 and F: inspect the Terraform source
    if tf_dir is not None:
        tf_dir = Path(tf_dir)
        declared = set()
        for f in sorted(tf_dir.glob("*.tf")):
            text = f.read_text(encoding="utf-8")
            declared |= set(RESOURCE_DECL.findall(text))
            for rx, what in FORBIDDEN:
                if rx.search(text):
                    _err(out, "F", f"FORBIDDEN_CONSTRUCT: {what} in {f.name}")
        missing = declared - set(c["resource_types"])
        extra = set(c["resource_types"]) - declared
        if missing:
            _err(out, "S4", "resources in the source but not declared: " + ", ".join(sorted(missing)))
        if extra:
            _err(out, "S4", "declared but not in the source: " + ", ".join(sorted(extra)))

    return out


def check_composition(bp: dict, catalog) -> list:
    """C1-C6."""
    out: list = []
    instances = bp.get("instances") or {}
    comps = {}
    for name, spec in instances.items():
        try:
            comps[name] = catalog.component(spec["component"])
        except KeyError as e:
            _err(out, "C5", str(e))
    if out:
        return out

    provides = {(i, p["port"]): p["type"] for i, m in comps.items() for p in (m.get("provides") or [])}
    provides[("sys", "lease_app")] = "workload.container/v1"
    bound: dict = {}
    dns_bindings = 0
    edges = set()

    for b in bp.get("bindings") or []:
        fi, fp = b["from"].split(".", 1)
        ti, tp = b["to"].split(".", 1)
        if fi == "sys":
            if fp != "dns":
                _err(out, "C1", f"unknown system port: {b['from']}")
                continue
            dns_bindings += 1
            if provides.get((ti, tp)) != "http.public/v1":
                _err(out, "C2", f"sys.dns must bind to http.public/v1, not {b['to']}")
            continue
        if fi not in comps:
            _err(out, "C1", f"binding from an unknown instance: {b['from']}")
            continue
        req = next((r for r in comps[fi].get("requires") or [] if r["port"] == fp), None)
        if req is None:
            _err(out, "C1", f"{fi} has no requires port '{fp}'")
            continue
        if (fi, fp) in bound:
            _err(out, "C1", f"{b['from']} has more than one binding")
        bound[(fi, fp)] = b["to"]
        ptype = provides.get((ti, tp))
        if ptype is None:
            _err(out, "C1", f"{b['to']} is not a provides port")
            continue
        if ptype != req["type"]:
            _err(out, "C2", f"{b['from']} requires {req['type']} but {b['to']} is {ptype}")
        if ti != "sys":
            edges.add((fi, ti))

    for i, m in comps.items():
        for r in m.get("requires") or []:
            if (i, r["port"]) not in bound:
                _err(out, "C1", f"{i}.{r['port']} ({r['type']}) has no binding")

    # C3: no cycles
    graph = {i: {t for (f, t) in edges if f == i} for i in comps}
    state: dict = {}

    def dfs(u):
        state[u] = 1
        for v in graph[u]:
            if state.get(v) == 1:
                return True
            if state.get(v) is None and dfs(v):
                return True
        state[u] = 2
        return False

    if any(state.get(u) is None and dfs(u) for u in comps):
        _err(out, "C3", "the dependency graph has a cycle")

    # C4
    if dns_bindings != 1:
        _err(out, "C4", f"exactly one binding to sys.dns is required, found {dns_bindings}")

    # C6: every instance supports each declared level
    for lv in bp.get("supported_levels") or []:
        for i, m in comps.items():
            if lv not in ((m.get("lifecycle") or {}).get("levels") or {}):
                _err(out, "C6", f"{i} does not support level {lv}")

    return out
