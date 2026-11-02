"""Kiểm tĩnh component (S1, S4-S7, F) và kiểm tra ghép Blueprint (C1-C6).

S2, S8 cần chạy Terraform nên nằm ở kiểm định động; ở đây chỉ kiểm phần không tốn tiền.
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
    (re.compile(r"\bprovider\s+\"[a-z0-9_]+\"\s*\{"), "khai báo provider trong component"),
    (re.compile(r"source\s*=\s*\"(git::|github\.com|https?://)"), "module nguồn ngoài chưa vendor"),
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
            _err(out, "S1", f"thiếu component.{k}")
    if out:
        return out
    if not NAME.match(c["name"]):
        _err(out, "S1", f"tên không hợp lệ: {c['name']}")
    if not SEMVER.match(str(c["version"])):
        _err(out, "S1", f"version không phải semver: {c['version']}")

    classes = registry["classes"]
    rtypes = registry["resource_types"]
    bclass = c["billing_class"]
    if bclass not in classes:
        _err(out, "S1", f"billing_class lạ: {bclass}")
        return out

    # S5: lớp tính phí trung thực theo Resource Type Registry
    for rt in c["resource_types"]:
        if rt not in rtypes:
            _err(out, "S5", f"loại tài nguyên ngoài Resource Type Registry: {rt}")
            continue
        forced = rtypes[rt].get("class")
        if forced and forced != "free" and forced != bclass:
            # Tài nguyên tốn tiền theo kiểu `forced` mà component khai lớp khác
            rank = {"free": 0, "stoppable": 1, "hourly_no_data": 2, "data": 3}
            if rank[forced] > rank[bclass] or forced == "data":
                _err(out, "S5", f"{rt} thuộc lớp {forced} nhưng component khai {bclass}")
        if rtypes[rt].get("data") and c.get("data_class") == "none":
            _err(out, "S5", f"{rt} chứa dữ liệu nhưng data_class = none")

    # S6: vòng đời khớp lớp
    lc = manifest.get("lifecycle") or {}
    valid_states = set(classes[bclass]["states"])
    levels = lc.get("levels") or {}
    for lv in ("awake", "deep"):
        if lv not in levels:
            _err(out, "S6", f"thiếu mức {lv}")
    for lv, st in levels.items():
        if lv not in LEVEL_NAMES:
            _err(out, "S6", f"mức lạ: {lv}")
        if st not in valid_states:
            _err(out, "S6", f"mức {lv} dùng trạng thái {st} không hợp lệ với lớp {bclass}")
    serving = lc.get("serving_states") or []
    if levels.get("awake") not in serving:
        _err(out, "S6", "trạng thái của mức awake phải thuộc serving_states")
    actions = {k: v.get("driver") for k, v in (lc.get("actions") or {}).items()}
    used = set(levels.values())
    if bclass in ("stoppable", "data") and "STOPPED" in used:
        for a in ("start", "stop"):
            if a not in actions:
                _err(out, "S6", f"lớp {bclass} dùng STOPPED nên cần driver '{a}'")
    if "SNAPSHOTTED" in used:
        if "snapshot" not in actions:
            _err(out, "S6", "dùng SNAPSHOTTED nên cần driver 'snapshot'")
        if not lc.get("restore_variable"):
            _err(out, "S6", "dùng SNAPSHOTTED nên cần restore_variable")
    for a, d in actions.items():
        if d not in registry["drivers"]:
            _err(out, "S6", f"driver ngoài Driver Registry: {d}")

    # S7: cổng có kiểu hợp lệ, thuộc tính tồn tại
    ptypes = registry["port_types"]
    for p in manifest.get("provides") or []:
        if p["type"] not in ptypes:
            _err(out, "S7", f"kiểu cổng lạ: {p['type']}")
            continue
        for attr in (p.get("attributes") or {}):
            if attr not in ptypes[p["type"]]:
                _err(out, "S7", f"cổng {p['port']}: thuộc tính {attr} không có trong {p['type']}")
    for r in manifest.get("requires") or []:
        if r["type"] not in ptypes:
            _err(out, "S7", f"kiểu cổng lạ: {r['type']}")
            continue
        if r.get("when", "present") not in ("present", "serving"):
            _err(out, "S7", f"cổng {r['port']}: when phải là present hoặc serving")
        for attr in (r.get("inputs") or {}):
            if attr not in ptypes[r["type"]]:
                _err(out, "S7", f"cổng {r['port']}: thuộc tính {attr} không có trong {r['type']}")
    outputs = manifest.get("outputs") or {}
    for a, spec in (lc.get("actions") or {}).items():
        tgt = spec.get("target")
        if tgt and outputs and not outputs.get(tgt, {}).get("stable"):
            _err(out, "S7", f"target của action {a} ({tgt}) phải là output stable")

    # S4 + F: đọc mã Terraform
    if tf_dir is not None:
        tf_dir = Path(tf_dir)
        declared = set()
        for f in sorted(tf_dir.glob("*.tf")):
            text = f.read_text(encoding="utf-8")
            declared |= set(RESOURCE_DECL.findall(text))
            for rx, what in FORBIDDEN:
                if rx.search(text):
                    _err(out, "F", f"FORBIDDEN_CONSTRUCT: {what} trong {f.name}")
        missing = declared - set(c["resource_types"])
        extra = set(c["resource_types"]) - declared
        if missing:
            _err(out, "S4", "tài nguyên có trong mã nhưng không khai báo: " + ", ".join(sorted(missing)))
        if extra:
            _err(out, "S4", "khai báo nhưng không có trong mã: " + ", ".join(sorted(extra)))

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
                _err(out, "C1", f"cổng hệ thống lạ: {b['from']}")
                continue
            dns_bindings += 1
            if provides.get((ti, tp)) != "http.public/v1":
                _err(out, "C2", f"sys.dns phải nối vào http.public/v1, không phải {b['to']}")
            continue
        if fi not in comps:
            _err(out, "C1", f"binding từ instance không tồn tại: {b['from']}")
            continue
        req = next((r for r in comps[fi].get("requires") or [] if r["port"] == fp), None)
        if req is None:
            _err(out, "C1", f"{fi} không có cổng requires '{fp}'")
            continue
        if (fi, fp) in bound:
            _err(out, "C1", f"{b['from']} có hơn một binding")
        bound[(fi, fp)] = b["to"]
        ptype = provides.get((ti, tp))
        if ptype is None:
            _err(out, "C1", f"{b['to']} không phải cổng provides")
            continue
        if ptype != req["type"]:
            _err(out, "C2", f"{b['from']} cần {req['type']} nhưng {b['to']} là {ptype}")
        if ti != "sys":
            edges.add((fi, ti))

    for i, m in comps.items():
        for r in m.get("requires") or []:
            if (i, r["port"]) not in bound:
                _err(out, "C1", f"{i}.{r['port']} ({r['type']}) chưa có binding")

    # C3: không chu trình
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
        _err(out, "C3", "đồ thị phụ thuộc có chu trình")

    # C4
    if dns_bindings != 1:
        _err(out, "C4", f"cần đúng một binding vào sys.dns, có {dns_bindings}")

    # C6: mức ngủ được mọi instance hỗ trợ
    for lv in bp.get("supported_levels") or []:
        for i, m in comps.items():
            if lv not in ((m.get("lifecycle") or {}).get("levels") or {}):
                _err(out, "C6", f"{i} không hỗ trợ mức {lv}")

    return out
