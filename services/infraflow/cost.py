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
    "redis_hour": {"small": 0.024, "medium": 0.048},
    "bastion_hour": 0.0053,
    "gpu_hour": {"small": 0.736, "medium": 1.052},
    "fargate_task_hour": {"small": 0.25 * 0.05056 + 0.5 * 0.00553, "medium": 0.5 * 0.05056 + 1 * 0.00553},
    "opensearch_hour": {"small": 0.045, "medium": 0.091},
    "rds_storage_hour": 20 * 0.131 / 730,
    "ebs_gb_hour": 0.096 / 730,
    "ebs_hour": 30 * 0.096 / 730,
    "snapshot_hour": 20 * 0.095 / 730,
    "ebs_snapshot_gb_hour": 0.055 / 730,
}
DATA_VOLUME_GB = {"small": 50, "medium": 200}


def _component_prices(size: str) -> dict:
    """Component name (without version) -> {state: USD per hour}. States not listed cost nothing."""
    p = PRICES
    return {
        "aws-network-basic": {},
        "aws-nat-egress": {"PRESENT": p["nat_gateway_hour"] + p["public_ipv4_hour"]},
        "aws-alb-https-entry": {"PRESENT": p["alb_hour"] + 2 * p["public_ipv4_hour"]},
        "aws-ec2-docker-app": {"RUNNING": p["ec2_hour"][size] + p["ebs_hour"], "STOPPED": p["ebs_hour"]},
        "aws-rds-postgres": {"RUNNING": p["rds_hour"][size] + p["rds_storage_hour"],
                             "STOPPED": p["rds_storage_hour"], "SNAPSHOTTED": p["snapshot_hour"]},
        "aws-elasticache-redis": {"PRESENT": p["redis_hour"][size]},
        "aws-ssm-bastion": {"RUNNING": p["bastion_hour"] + 8 * p["ebs_gb_hour"], "STOPPED": 8 * p["ebs_gb_hour"]},
        "aws-ec2-gpu-workbench": {"RUNNING": p["gpu_hour"][size] + 100 * p["ebs_gb_hour"],
                                  "STOPPED": 100 * p["ebs_gb_hour"]},
        # Snapshots are billed for the blocks in use; the full size is an upper bound.
        "aws-ebs-volume": {"RUNNING": DATA_VOLUME_GB[size] * p["ebs_gb_hour"],
                           "SNAPSHOTTED": DATA_VOLUME_GB[size] * p["ebs_snapshot_gb_hour"]},
        "aws-alb-ip-entry": {"PRESENT": p["alb_hour"] + 2 * p["public_ipv4_hour"]},
        "aws-ecs-fargate-service": {"RUNNING": p["fargate_task_hour"][size]},
        "aws-opensearch-domain": {"PRESENT": p["opensearch_hour"][size] + 10 * 0.146 / 730},
        "aws-sqs-queue": {},  # per request; nothing while idle
    }


class PriceModel:
    """Hourly price of each instance of a Blueprint, by state. Instances of billing class
    hourly_no_data are billed by the started hour for each continuous interval of existence."""

    def __init__(self, graph, size: str = "small"):
        table = _component_prices(size)
        self.graph = graph
        self.prices = {u: table.get(i.component.split("@", 1)[0], {}) for u, i in graph.instances.items()}
        self.rounded = {u for u, i in graph.instances.items() if i.billing_class == "hourly_no_data"}

    def hourly(self, instance: str, state: str) -> float:
        return self.prices[instance].get(state, 0.0)

    def level(self, level: str) -> float:
        """Hourly price of the whole Environment held at one level."""
        vec = self.graph.level_vector(level)
        return round(sum(self.hourly(u, s) for u, s in vec.items()), 4)


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


def _cost(intervals: dict, prices: PriceModel) -> float:
    total = 0.0
    for u, segs in intervals.items():
        for t0, t1, s in segs:
            rate = prices.hourly(u, s)
            h = (t1 - t0).total_seconds() / 3600
            if u in prices.rounded and rate > 0:
                h = math.ceil(h - 1e-9)
            total += h * rate
    return round(total, 4)


def scenarios(graph, log: list, start: datetime, end: datetime, size: str = "small",
              policy: dict | None = None) -> dict:
    """always_on keeps the awake level; stop_only stops the stoppable instances outside the
    schedule and keeps everything else; infraflow replays the transition log."""
    policy = {**DEFAULT_POLICY, **(policy or {})}
    prices = PriceModel(graph, size)
    awake = graph.level_vector("awake")
    initial = graph.level_vector("prepared")

    real = _intervals(log, initial, start, end)
    always = {u: [(start, end, s)] for u, s in awake.items()}

    # on_demand has no schedule; the default schedule is the reference for stop_only
    ref = policy if policy.get("schedule") else DEFAULT_POLICY
    stoppable = {u for u, i in graph.instances.items() if i.billing_class == "stoppable"}
    stop_only = {u: [] for u in awake}
    t = start
    step = timedelta(minutes=15)
    while t < end:
        t2 = min(t + step, end)
        on = in_schedule(ref, t)
        for u, s in awake.items():
            st = "STOPPED" if (u in stoppable and not on) else s
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

    c247, cstop, creal = _cost(always, prices), _cost(stop_only, prices), _cost(real, prices)
    return {
        "from": start.isoformat(), "to": end.isoformat(), "currency": "USD", "estimate": True,
        "always_on": c247, "stop_only": cstop, "infraflow": creal,
        "saving_vs_always_on_pct": round(100 * (1 - creal / c247), 1) if c247 else None,
        "saving_vs_stop_only_pct": round(100 * (1 - creal / cstop), 1) if cstop else None,
    }
