"""CLI của InfraFlow: python -m infraflow.cli <lệnh> ...

  check            kiểm tĩnh mọi component + kiểm tra ghép + model checking mọi Blueprint trong catalog
  validate-blueprint FILE   kiểm một blueprint.yaml (Compose) dựa trên catalog hiện có
  plan             in lifecycle plan giữa hai mức và kết quả model checking
  compile          sinh root module Terraform (+ providers.tf, + levels/*.tfvars.json)
  bundle           đóng gói catalog thành services/infraflow/catalog.json (cho Lambda, CodeBuild)
  validate-plan    Plan Validator trên JSON của `terraform show -json`
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .ics import checker, compiler, planner, static, validator
from .ics.catalog import load_bundle, load_from_repo
from .ics.model import build_graph, make_state

REPO = Path(__file__).resolve().parents[2]


def _catalog(args):
    if getattr(args, "catalog", None):
        return load_bundle(args.catalog)
    return load_from_repo(args.root)


def _print_check(rep: dict) -> None:
    for c in rep["checks"]:
        mark = "ĐẠT " if c["passed"] else "LỖI "
        print(f"  [{mark}] {c['code']:<6} {c['name']}")
        if not c["passed"] and c.get("detail"):
            d = c["detail"]
            print(f"           {d.get('rule')}: {d.get('message')}")
            for line in d.get("trace") or []:
                print(f"             {line}")


def cmd_check(args) -> int:
    cat = _catalog(args)
    ok = True
    print("== Kiểm tĩnh component (S1, S4-S7, F)")
    for ref, m in sorted(cat.components.items()):
        tf_dir = Path(args.root) / m["_dir"] if "_dir" in m and not getattr(args, "catalog", None) else None
        errs = static.check_component(m, cat.registry, tf_dir)
        print(f"  {ref:<32} {'ĐẠT' if not errs else 'LỖI'}")
        for e in errs:
            print(f"      {e['code']}: {e['message']}")
        ok &= not errs
    print("== Blueprint")
    for ref, bp in sorted(cat.blueprints.items()):
        ok &= _check_bp(cat, bp, ref)
    return 0 if ok else 1


def _check_bp(cat, bp, label) -> bool:
    print(f"-- {label}")
    errs = static.check_composition(bp, cat)
    for e in errs:
        print(f"  [LỖI ] {e['code']:<6} {e['message']}")
    if errs:
        return False
    print("  [ĐẠT ] C1-C6  kiểm tra ghép")
    g = build_graph(cat, blueprint=bp)
    rep = checker.check_blueprint(g)
    _print_check(rep)
    print(f"  => {'ĐẠT' if rep['passed'] else 'KHÔNG ĐẠT'} ({rep['states_explored']} trạng thái đã duyệt)")
    return rep["passed"]


def cmd_validate_blueprint(args) -> int:
    import yaml

    cat = _catalog(args)
    bp = yaml.safe_load(Path(args.file).read_text(encoding="utf-8"))
    return 0 if _check_bp(cat, bp, args.file) else 1


def cmd_plan(args) -> int:
    cat = _catalog(args)
    g = build_graph(cat, args.blueprint)
    start_vec = g.level_vector(args.frm)
    dns = "APP" if args.frm == "awake" else "SLEEP"
    p = planner.plan(g, start_vec, args.to, dns, keep_final_backup=not args.no_backup)
    r = checker.check_plan(g, make_state(g, start_vec, dns, args.frm == "awake"), p)
    p["model_check"] = {"passed": r["passed"], "states_explored": r["states_explored"]}
    if not r["passed"]:
        p["model_check"]["violation"] = r["violation"]
    print(json.dumps(p, ensure_ascii=False, indent=2))
    return 0 if r["passed"] else 1


def cmd_compile(args) -> int:
    cat = _catalog(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "main.tf").write_text(compiler.compile_main(cat, args.blueprint, args.components_rel), encoding="utf-8")
    if args.providers:
        (out / "providers.tf").write_text(compiler.compile_providers(
            region=args.region, env_id=args.env_id, lease_id=args.lease_id, org_id=args.org_id,
            state_bucket=args.state_bucket, state_key=args.state_key, profile=args.profile,
            assume_role_arn=args.assume_role_arn, external_id=args.external_id), encoding="utf-8")
    if args.levels:
        g = build_graph(cat, args.blueprint)
        lv_dir = out / "levels"
        lv_dir.mkdir(exist_ok=True)
        for lv in list(g.supported_levels) + ["prepared"]:
            (lv_dir / f"{lv}.tfvars.json").write_text(
                json.dumps(compiler.level_tfvars(g, lv), indent=2) + "\n", encoding="utf-8")
    print(compiler.compiled_hash(cat, args.blueprint))
    return 0


def cmd_bundle(args) -> int:
    cat = load_from_repo(args.root)
    dest = Path(args.out)
    dest.write_text(cat.to_json() + "\n", encoding="utf-8")
    print(f"đã ghi {dest} ({len(cat.components)} component, {len(cat.blueprints)} blueprint)")
    return 0


def cmd_validate_plan(args) -> int:
    cat = _catalog(args)
    raw = Path(args.plan_json).read_bytes()
    res = validator.validate(
        json.loads(raw), cat, args.blueprint, env_id=args.env_id,
        allowed_instances=json.loads(args.allowed), snapshots_ok=json.loads(args.snapshots),
        allow_data_loss=args.allow_data_loss, expected_hash=args.expected_hash,
        plan_sha256="sha256:" + hashlib.sha256(raw).hexdigest())
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["passed"] else 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="infraflow")
    ap.add_argument("--root", default=str(REPO), help="thư mục gốc repo (đọc YAML)")
    ap.add_argument("--catalog", help="dùng catalog.json thay vì đọc YAML")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check")
    s = sub.add_parser("validate-blueprint")
    s.add_argument("file")

    s = sub.add_parser("plan")
    s.add_argument("--blueprint", default="web-db@1.0.0")
    s.add_argument("--from", dest="frm", required=True)
    s.add_argument("--to", required=True)
    s.add_argument("--no-backup", action="store_true")

    s = sub.add_parser("compile")
    s.add_argument("--blueprint", default="web-db@1.0.0")
    s.add_argument("--components-rel", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--levels", action="store_true")
    s.add_argument("--providers", action="store_true")
    for k in ("region", "env-id", "lease-id", "org-id", "state-bucket", "state-key", "profile",
              "assume-role-arn", "external-id"):
        s.add_argument(f"--{k}")

    s = sub.add_parser("bundle")
    s.add_argument("--out", default=str(Path(__file__).resolve().parent / "catalog.json"))

    s = sub.add_parser("validate-plan")
    s.add_argument("plan_json")
    s.add_argument("--blueprint", default="web-db@1.0.0")
    s.add_argument("--env-id", required=True)
    s.add_argument("--allowed", default="[]")
    s.add_argument("--snapshots", default="[]")
    s.add_argument("--allow-data-loss", action="store_true")
    s.add_argument("--expected-hash")

    args = ap.parse_args(argv)
    fn = {"check": cmd_check, "validate-blueprint": cmd_validate_blueprint, "plan": cmd_plan,
          "compile": cmd_compile, "bundle": cmd_bundle, "validate-plan": cmd_validate_plan}[args.cmd]
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
