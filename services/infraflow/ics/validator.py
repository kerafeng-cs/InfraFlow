"""Plan Validator (TD mục 11.2): chạy giữa `terraform plan -out=plan.out` và `terraform apply plan.out`.

Đầu vào: JSON của `terraform show -json plan.out`.
Đầu ra: {"passed": bool, "plan_sha256": ..., "violations": [{"rule", "address", "reason"}]}.

Luật cài đặt ở đây: V1, V2, V3, V4, V5, V6, V8, V9.
(V7 do model checker đảm nhận trước khi giao plan; V10-V12 thuộc mức C/D.)
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

    # V9: compiled_hash khớp chứng nhận
    if expected_hash:
        got = ((plan_json.get("planned_values") or {}).get("outputs") or {}).get("compiled_hash", {}).get("value")
        if got is None:
            got = (((plan_json.get("configuration") or {}).get("root_module") or {}).get("outputs") or {}) \
                .get("compiled_hash", {}).get("expression", {}).get("constant_value")
        if got != expected_hash:
            bad("V9", "output.compiled_hash", f"compiled_hash {got} khác {expected_hash}")

    for rc in plan_json.get("resource_changes") or []:
        if rc.get("mode", "managed") != "managed":
            continue
        actions = rc["change"]["actions"]
        if actions in (["no-op"], ["read"]):
            continue
        addr = rc["address"]
        rtype = rc["type"]
        inst = _instance_of(rc)

        # V1: mọi thay đổi thuộc một instance
        if inst is None or inst not in bp["instances"]:
            bad("V1", addr, "thay đổi không thuộc instance nào của Blueprint")
            continue

        # V2: chỉ instance được phép trong bước này
        if inst not in allowed:
            bad("V2", addr, f"instance {inst} không được phép thay đổi ở bước này ({actions})")

        # V8: loại tài nguyên nằm trong manifest và Registry
        if rtype not in registry["resource_types"] or rtype not in manifest_types[inst]:
            bad("V8", addr, f"loại {rtype} không có trong manifest của {inst} hoặc Registry")

        is_delete = "delete" in actions
        is_create = "create" in actions
        is_data = rtype in data_types

        # V4: không replace tài nguyên dữ liệu
        if is_data and is_delete and is_create:
            bad("V4", addr, "replace tài nguyên dữ liệu (xóa rồi tạo lại = mất dữ liệu)")
        # V3: xóa dữ liệu phải có snapshot available của chính operation
        elif is_data and is_delete and inst not in snapshots_ok and not allow_data_loss:
            bad("V3", addr, "xóa tài nguyên dữ liệu khi chưa có snapshot available của operation này")

        # V5: tài nguyên tạo mới có đủ tag đúng (chỉ với loại có tags_all)
        after = rc["change"].get("after") or {}
        if is_create and "tags_all" in after:
            tags = after.get("tags_all") or {}
            for k in REQUIRED_TAGS:
                if k not in tags:
                    bad("V5", addr, f"thiếu tag {k}")
            if tags.get("infraflow:env_id") not in (None, env_id):
                bad("V5", addr, f"tag env_id = {tags.get('infraflow:env_id')} khác {env_id}")

        # V6: tài nguyên sửa/xóa mang đúng env_id
        before = rc["change"].get("before") or {}
        if (is_delete or "update" in actions) and "tags_all" in before:
            tag = (before.get("tags_all") or {}).get("infraflow:env_id")
            if tag != env_id:
                bad("V6", addr, f"tài nguyên mang env_id {tag}, không phải {env_id}")

    return {"passed": not v, "plan_sha256": plan_sha256, "violations": v}
