"""Plan Validator: runs between `terraform plan -out=plan.out` and `terraform apply plan.out`.

Input: the JSON of `terraform show -json plan.out`.
Output: {"passed": bool, "plan_sha256": ..., "violations": [{"rule", "address", "reason"}]}.

Rules implemented here: V1, V2, V3, V4, V5, V6, V8, V9.
V7 (ordering safety) is enforced by the model checker before a plan is issued.
"""

from __future__ import annotations

import re

MODULE_RE = re.compile(r"^module\.([a-z][a-z0-9_]*)\[0\]")
REQUIRED_TAGS = ("infraflow:managed", "infraflow:env_id", "infraflow:lease_id", "infraflow:org_id")


def _instance_of(rc: dict) -> str | None:
    m = MODULE_RE.match(rc.get("module_address") or rc.get("address", ""))
    return m.group(1) if m else None


def validate(plan_json: dict, catalog, blueprint_ref: str, *, env_id: str, allowed_instances: list,
             snapshots_ok: list = (), allow_data_loss: bool = False, expected_hash: str | None = None,
             plan_sha256: str | None = None) -> dict:
    bp = catalog.blueprint(blueprint_ref)
    registry = catalog.registry
    data_types = {t for t, spec in registry["resource_types"].items() if spec.get("data")}
    manifest_types = {
        inst: set(catalog.component(spec["component"])["component"]["resource_types"])
        for inst, spec in bp["instances"].items()
    }
    allowed = set(allowed_instances)
    v = []

    def bad(rule, addr, reason):
        v.append({"rule": rule, "address": addr, "reason": reason})

    # V9: compiled_hash matches the certified build
    if expected_hash:
        got = ((plan_json.get("planned_values") or {}).get("outputs") or {}).get("compiled_hash", {}).get("value")
        if got is None:
            got = (((plan_json.get("configuration") or {}).get("root_module") or {}).get("outputs") or {}) \
                .get("compiled_hash", {}).get("expression", {}).get("constant_value")
        if got != expected_hash:
            bad("V9", "output.compiled_hash", f"compiled_hash {got} differs from {expected_hash}")

    for rc in plan_json.get("resource_changes") or []:
        if rc.get("mode", "managed") != "managed":
            continue
        actions = rc["change"]["actions"]
        if actions in (["no-op"], ["read"]):
            continue
        addr = rc["address"]
        rtype = rc["type"]
        inst = _instance_of(rc)

        # V1: every change belongs to an instance
        if inst is None or inst not in bp["instances"]:
            bad("V1", addr, "change does not belong to any Blueprint instance")
            continue

        # V2: only instances permitted in this step may change
        if inst not in allowed:
            bad("V2", addr, f"instance {inst} may not change in this step ({actions})")

        # V8: resource type is in the component manifest and the Registry
        if rtype not in registry["resource_types"] or rtype not in manifest_types[inst]:
            bad("V8", addr, f"type {rtype} is not in the manifest of {inst} or in the Registry")

        is_delete = "delete" in actions
        is_create = "create" in actions
        is_data = rtype in data_types

        # V4: no replacement of data resources
        if is_data and is_delete and is_create:
            bad("V4", addr, "replacing a data resource (delete then create loses data)")
        # V3: deleting data requires an available snapshot taken by this operation
        elif is_data and is_delete and inst not in snapshots_ok and not allow_data_loss:
            bad("V3", addr, "deleting a data resource without an available snapshot from this operation")

        # V5: created resources carry the required tags (types with tags_all only)
        after = rc["change"].get("after") or {}
        if is_create and "tags_all" in after:
            tags = after.get("tags_all") or {}
            for k in REQUIRED_TAGS:
                if k not in tags:
                    bad("V5", addr, f"missing tag {k}")
            if tags.get("infraflow:env_id") not in (None, env_id):
                bad("V5", addr, f"tag env_id = {tags.get('infraflow:env_id')} differs from {env_id}")

        # V6: updated or deleted resources carry the expected env_id
        before = rc["change"].get("before") or {}
        if (is_delete or "update" in actions) and "tags_all" in before:
            tag = (before.get("tags_all") or {}).get("infraflow:env_id")
            if tag != env_id:
                bad("V6", addr, f"resource has env_id {tag}, not {env_id}")

    return {"passed": not v, "plan_sha256": plan_sha256, "violations": v}
