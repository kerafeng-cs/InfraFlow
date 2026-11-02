"""Trình biên dịch Blueprint (TD mục 5.2): blueprint.yaml + component -> root module Terraform.

Nguyên tắc: InfraFlow KHÔNG sinh logic tài nguyên, chỉ sinh mã nối tất định:
- mỗi instance là một `module` bật/tắt bằng `count = var.<instance>_present ? 1 : 0`;
- input của module lấy từ output của phía cung cấp theo binding;
- cùng đầu vào thì cùng từng byte đầu ra (golden test).

Biến `<instance>_present` cố ý KHÔNG có giá trị mặc định: quên truyền thì Terraform báo lỗi,
không lặng lẽ hiểu là false rồi xóa hạ tầng.
"""

from __future__ import annotations

import hashlib
import json
import re

COMPILER_VERSION = "1"

# Thuộc tính của sys.lease_app (workload.container/v1) -> biến gốc
LEASE_APP_VARS = {
    "image": ("app_image", "string", "public.ecr.aws/nginx/nginx:stable"),
    "port": ("app_port", "number", 80),
    "health_path": ("app_health_path", "string", "/"),
}

# Biến hệ thống mà component có thể xin (system_inputs)
SYSTEM_VARS = {
    "name_prefix": ("string", None, "Tiền tố tên tài nguyên, bằng env_id"),
    "env_id": ("string", None, "Định danh Environment"),
    "certificate_arn": ("string", "null", "Chứng chỉ ACM wildcard; null = chỉ HTTP"),
}


def _hcl(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    raise TypeError(f"không biểu diễn được {v!r}")


def compiled_hash(catalog, blueprint_ref: str) -> str:
    bp = catalog.blueprint(blueprint_ref)
    comps = {}
    for spec in bp["instances"].values():
        m = dict(catalog.component(spec["component"]))
        m.pop("_dir", None)
        comps[spec["component"]] = m
    blob = json.dumps({"compiler": COMPILER_VERSION, "blueprint": bp, "components": comps},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


def compile_main(catalog, blueprint_ref: str, components_rel: str) -> str:
    """Sinh main.tf. components_rel: đường dẫn tương đối từ thư mục root tới thư mục components."""
    bp = catalog.blueprint(blueprint_ref)
    meta = bp["blueprint"]
    h = compiled_hash(catalog, blueprint_ref)
    L = []
    w = L.append

    w("# Sinh tự động bởi trình biên dịch Blueprint của InfraFlow. KHÔNG SỬA TAY.")
    w(f"# blueprint: {meta['name']}@{meta['version']}")
    w(f"# compiled_hash: {h}")
    w("")

    # ---- biến hệ thống ----
    needed_sys = []
    for spec in bp["instances"].values():
        for sv in catalog.component(spec["component"])["component"].get("system_inputs", []):
            if sv not in needed_sys:
                needed_sys.append(sv)
    for sv in sorted(needed_sys, key=lambda x: list(SYSTEM_VARS).index(x)):
        typ, default, desc = SYSTEM_VARS[sv]
        w(f'variable "{sv}" {{')
        w(f"  type        = {typ}")
        w(f"  description = {_hcl(desc)}")
        if default is not None:
            w(f"  default     = {default}")
        w("}")
        w("")

    # ---- tham số Blueprint ----
    for pname, pspec in sorted((bp.get("parameters") or {}).items()):
        w(f'variable "{pname}" {{')
        w(f"  type    = {pspec.get('type', 'string')}")
        if "default" in pspec:
            w(f"  default = {_hcl(pspec['default'])}")
        w("}")
        w("")

    # ---- cấu hình ứng dụng của Lease (sys.lease_app) ----
    uses_lease_app = any(b["to"] == "sys.lease_app" for b in bp.get("bindings", []))
    if uses_lease_app:
        for attr, (var, typ, default) in LEASE_APP_VARS.items():
            w(f'variable "{var}" {{')
            w(f"  type    = {typ}")
            w(f"  default = {_hcl(default)}")
            w("}")
            w("")

    # ---- công tắc từng instance ----
    for inst, spec in bp["instances"].items():
        comp = catalog.component(spec["component"])
        w(f'variable "{inst}_present" {{')
        w("  type        = bool")
        w(f'  description = "Bật/tắt instance {inst} ({comp["component"]["billing_class"]})"')
        w("}")
        w("")
        if (comp.get("lifecycle") or {}).get("restore_variable"):
            w(f'variable "{inst}_restore_snapshot" {{')
            w("  type    = string")
            w("  default = null")
            w("}")
            w("")

    # ---- module ----
    bindings = {}
    for b in bp.get("bindings", []):
        bindings[b["from"]] = b["to"]

    for inst, spec in bp["instances"].items():
        comp = catalog.component(spec["component"])
        c = comp["component"]
        w(f"# ---------- {inst}: {spec['component']} ({c['billing_class']}) ----------")
        w(f'module "{inst}" {{')
        w(f'  source = "{components_rel}/{c["name"]}/{c["version"]}"')
        w(f"  count  = var.{inst}_present ? 1 : 0")
        w("")
        for sv in c.get("system_inputs", []):
            w(f"  {sv} = var.{sv}")
        for pname, pval in sorted((spec.get("parameters") or {}).items()):
            if isinstance(pval, str) and pval.startswith("${param.") and pval.endswith("}"):
                w(f"  {pname} = var.{pval[len('${param.'):-1]}")
            else:
                w(f"  {pname} = {_hcl(pval)}")
        rv = (comp.get("lifecycle") or {}).get("restore_variable")
        if rv:
            w(f"  {rv} = var.{inst}_restore_snapshot")

        for req in comp.get("requires") or []:
            inputs = req.get("inputs") or {}
            src = bindings.get(f"{inst}.{req['port']}")
            w("")
            w(f"  # binding: {inst}.{req['port']} <- {src} ({req['type']}, {req.get('when', 'present')})")
            if not inputs or src is None:
                continue
            t_inst, t_port = src.split(".", 1)
            if t_inst == "sys" and t_port == "lease_app":
                for attr, var in inputs.items():
                    w(f"  {var} = var.{LEASE_APP_VARS[attr][0]}")
                continue
            prov = next(p for p in catalog.component(bp["instances"][t_inst]["component"])["provides"]
                        if p["port"] == t_port)
            for attr, var in inputs.items():
                out = prov["attributes"][attr]
                w(f"  {var} = one(module.{t_inst}[*].{out})")
        w("}")
        w("")

    # ---- output ----
    for inst in bp["instances"]:
        w(f'output "{inst}" {{')
        w(f"  value = one(module.{inst}[*])")
        w("}")
        w("")
    dns_src = bindings.get("sys.dns")
    if dns_src:
        t_inst, t_port = dns_src.split(".", 1)
        prov = next(p for p in catalog.component(bp["instances"][t_inst]["component"])["provides"]
                    if p["port"] == t_port)
        w('output "public_endpoint" {')
        w(f"  value = one(module.{t_inst}[*].{prov['attributes']['dns_name']})")
        w("}")
        w("")
    w('output "compiled_hash" {')
    w(f'  value = "{h}"')
    w("}")

    return _align("\n".join(L).rstrip() + "\n")


_ASSIGN = re.compile(r"^(\s+)([A-Za-z0-9_\"]+|\"[^\"]+\")(\s*)=\s(.*)$")


def _align(text: str) -> str:
    """Căn dấu = như `terraform fmt` cho các dòng gán liền nhau cùng mức thụt lề."""
    lines = text.split("\n")
    out, run = [], []

    def flush():
        if run:
            width = max(len(m.group(2)) for m in run)
            for m in run:
                out.append(f"{m.group(1)}{m.group(2).ljust(width)} = {m.group(4)}")
            run.clear()

    for line in lines:
        m = _ASSIGN.match(line)
        if m and (not run or run[0].group(1) == m.group(1)) and "{" not in m.group(4)[-1:]:
            run.append(m)
            continue
        flush()
        m2 = _ASSIGN.match(line)
        if m2 and "{" not in m2.group(4)[-1:]:
            run.append(m2)
        else:
            out.append(line)
    flush()
    return "\n".join(out)


def compile_providers(region: str, env_id: str, lease_id: str, org_id: str, state_bucket: str | None = None,
                      state_key: str | None = None, profile: str | None = None,
                      assume_role_arn: str | None = None, external_id: str | None = None) -> str:
    L = ["# Sinh tự động. KHÔNG SỬA TAY.", "terraform {", '  required_version = ">= 1.10"', "  required_providers {",
         '    aws    = { source = "hashicorp/aws", version = "~> 6.0" }',
         '    random = { source = "hashicorp/random", version = "~> 3.6" }', "  }"]
    if state_bucket:
        L += ['  backend "s3" {', f"    bucket       = {_hcl(state_bucket)}", f"    key          = {_hcl(state_key)}",
              f"    region       = {_hcl(region)}", "    use_lockfile = true", "    encrypt      = true", "  }"]
    L += ["}", "", 'provider "aws" {', f"  region = {_hcl(region)}"]
    if profile:
        L.append(f"  profile = {_hcl(profile)}")
    if assume_role_arn:
        L += ["  assume_role {", f"    role_arn    = {_hcl(assume_role_arn)}", f"    external_id = {_hcl(external_id)}", "  }"]
    L += ["  default_tags {", "    tags = {",
          f'      "infraflow:managed"  = "true"',
          f'      "infraflow:env_id"   = {_hcl(env_id)}',
          f'      "infraflow:lease_id" = {_hcl(lease_id)}',
          f'      "infraflow:org_id"   = {_hcl(org_id)}',
          "    }", "  }", "}"]
    return "\n".join(L) + "\n"


def level_tfvars(graph, level: str) -> dict:
    from .model import ABSENT, SNAPSHOTTED

    vec = graph.level_vector(level)
    return {f"{u}_present": vec[u] not in (ABSENT, SNAPSHOTTED) for u in graph.order}
