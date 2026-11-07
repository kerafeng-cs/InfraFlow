"""Three cost scenarios over the same interval [from, to).

Unit prices are ESTIMATES for ap-southeast-1 in USD, used to compare the scenarios with each
other. Actual cost comes from Cost Explorer, filtered by tag.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from .desired import DEFAULT_POLICY, in_schedule, parse_ts

PRICES = {
    "nat_gateway_hour": 0.059,
    "public_ipv4_hour": 0.005,
    "alb_hour": 0.0252,
    "ec2_hour": {"small": 0.0264, "medium": 0.0528},
    "rds_hour": {"small": 0.025, "medium": 0.051},
    "rds_storage_hour": 20 * 0.131 / 730,
    "ebs_hour": 30 * 0.096 / 730,
    "snapshot_hour": 20 * 0.095 / 730,
}
ROUNDED = {"egress", "entry"}  # billed by the started hour for each continuous interval of existence


def hourly(instance: str, state: str, size: str) -> float:
    p = PRICES
    if instance == "egress" and state == "PRESENT":
        return p["nat_gateway_hour"] + p["public_ipv4_hour"]
    if instance == "entry" and state == "PRESENT":
        return p["alb_hour"] + 2 * p["public_ipv4_hour"]
    if instance == "app":
        if state == "RUNNING":
            return p["ec2_hour"][size] + p["ebs_hour"]
        if state == "STOPPED":
            return p["ebs_hour"]
    if instance == "database":
        if state == "RUNNING":
            return p["rds_hour"][size] + p["rds_storage_hour"]
        if state == "STOPPED":
            return p["rds_storage_hour"]
        if state == "SNAPSHOTTED":
            return p["snapshot_hour"]
    return 0.0


AWAKE = {"network": "PRESENT", "egress": "PRESENT", "database": "RUNNING", "app": "RUNNING", "entry": "PRESENT"}


def _intervals(log: list, initial: dict, start: datetime, end: datetime):
    """Transition log -> {instance: [(t0, t1, state)]}."""
    state = dict(initial)
    cur_t = start
    out = {u: [] for u in state}
    for e in sorted(log, key=lambda x: x["at"]):
        at = parse_ts(e["at"])
        if at < start:
            state[e["instance"]] = e["to"]
            continue
        if at >= end:
            break
        for u in state:
            out[u].append((cur_t, at, state[u]))
        state[e["instance"]] = e["to"]
        cur_t = at
    for u in state:
        out[u].append((cur_t, end, state[u]))
    # merge adjacent intervals with the same state
    for u in out:
        merged = []
        for t0, t1, s in out[u]:
            if t1 <= t0:
                continue
            if merged and merged[-1][2] == s and merged[-1][1] == t0:
                merged[-1] = (merged[-1][0], t1, s)
            else:
                merged.append((t0, t1, s))
        out[u] = merged
    return out


def _cost(intervals: dict, size: str) -> float:
    total = 0.0
    for u, segs in intervals.items():
        for t0, t1, s in segs:
            h = (t1 - t0).total_seconds() / 3600
            if u in ROUNDED and hourly(u, s, size) > 0:
                h = math.ceil(h - 1e-9)
            total += h * hourly(u, s, size)
    return round(total, 4)


def scenarios(log: list, start: datetime, end: datetime, size: str = "small", policy: dict | None = None) -> dict:
    policy = {**DEFAULT_POLICY, **(policy or {})}
    initial = {u: "ABSENT" for u in AWAKE}
    initial["network"] = "PRESENT"

    real = _intervals(log, initial, start, end)
    always = {u: [(start, end, s)] for u, s in AWAKE.items()}

    # Scheduled stop of EC2 and RDS only (on_demand uses the default reference schedule)
    ref = policy if policy.get("schedule") else DEFAULT_POLICY
    stop_only = {u: [] for u in AWAKE}
    t = start
    step = timedelta(minutes=15)
    while t < end:
        t2 = min(t + step, end)
        on = in_schedule(ref, t)
        for u, s in AWAKE.items():
            st = s if (on or u in ("network", "egress", "entry")) else "STOPPED"
            stop_only[u].append((t, t2, st))
        t = t2
    for u in stop_only:  # merge
        merged = []
        for seg in stop_only[u]:
            if merged and merged[-1][2] == seg[2] and merged[-1][1] == seg[0]:
                merged[-1] = (merged[-1][0], seg[1], seg[2])
            else:
                merged.append(seg)
        stop_only[u] = merged

    c247, cstop, creal = _cost(always, size), _cost(stop_only, size), _cost(real, size)
    return {
        "from": start.isoformat(), "to": end.isoformat(), "currency": "USD", "estimate": True,
        "always_on": c247, "stop_only": cstop, "infraflow": creal,
        "saving_vs_always_on_pct": round(100 * (1 - creal / c247), 1) if c247 else None,
        "saving_vs_stop_only_pct": round(100 * (1 - creal / cstop), 1) if cstop else None,
    }
