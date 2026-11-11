"""Classification of Blueprints.

A Blueprint declares only its category (and example use cases). Every other axis is derived
from the components it composes, so the classification cannot disagree with what is deployed:

- exposure     public (sys.dns is bound to an instance) or none
- workload     whether an instance runs the Lease's container image (binds sys.lease_app)
- data         the strongest data class among the instances: persistent (snapshotted, survives
               every level), retained (kept while asleep, not backed up), ephemeral (lost on
               sleep), else stateless
- sleep        the deepest supported level, and which billing classes the Blueprint contains
- cost         estimated USD per hour at each supported level, for each size the Blueprint accepts
"""

from __future__ import annotations

from .cost import PriceModel
from .ics.model import build_graph

DATA_ORDER = ("stateless", "ephemeral", "retained", "persistent")
SLEEP_ORDER = ("awake", "shallow", "deep", "hibernate")


def classify(catalog, ref: str) -> dict:
    bp = catalog.blueprint(ref)
    meta = bp["blueprint"]
    g = build_graph(catalog, ref)
    declared = meta.get("classification") or {}

    data = "stateless"
    for inst in g.instances.values():
        kind = inst.data_class if inst.data_class in DATA_ORDER else "stateless"
        if DATA_ORDER.index(kind) > DATA_ORDER.index(data):
            data = kind

    levels = [lv for lv in SLEEP_ORDER if lv in g.supported_levels]
    sizes = list(((bp.get("parameters") or {}).get("size") or {}).get("enum") or ["small"])
    hourly = {}
    for size in sizes:
        prices = PriceModel(g, size)
        hourly[size] = {lv: prices.level(lv) for lv in levels}
    deepest = levels[-1]
    awake = hourly[sizes[0]]["awake"]
    classes = sorted({i.billing_class for i in g.instances.values()})

    return {
        "category": declared.get("category"),
        "use_cases": list(declared.get("use_cases") or []),
        "exposure": "public" if g.dns_target else "none",
        "workload": any(b["to"] == "sys.lease_app" for b in bp.get("bindings", [])),
        "data": data,
        "deepest_level": deepest,
        "billing_classes": classes,
        "hourly_usd": hourly,
        "asleep_saving_pct": round(100 * (1 - hourly[sizes[0]][deepest] / awake), 1) if awake else None,
    }
