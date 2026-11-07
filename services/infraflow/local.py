"""Local executor for a compiled Terraform root module.

Runs Sleep and Wake from a workstation without the hosted platform. It uses the same planner,
model checker, Plan Validator and drivers as the platform; the only difference is that Terraform
runs as a subprocess instead of in CodeBuild.

  python -m infraflow.local status --dir ../live/dev/web-db-manual
  python -m infraflow.local go awake --dir ../live/dev/web-db-manual
  python -m infraflow.local go deep  --dir ../live/dev/web-db-manual
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from . import controller, drivers
from .ics import checker, planner, validator
from .ics.catalog import load_from_repo
from .ics.model import build_graph, make_state
from .store import MemoryStore, set_store

REPO = Path(__file__).resolve().parents[2]


def tf(dir_, *args, capture=False):
    cmd = ["terraform", f"-chdir={dir_}", *args]
    print("  $", " ".join(cmd))
    if capture:
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    subprocess.run(cmd, check=True)


def load_env(dir_: Path) -> dict:
    return json.loads((dir_ / "env.auto.tfvars.json").read_text())


def observe(graph, ctx):
    return drivers.observe_all(graph, ctx)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="infraflow.local")
    ap.add_argument("cmd", choices=["status", "go"])
    ap.add_argument("level", nargs="?", choices=["awake", "deep", "hibernate", "prepared", "reclaimed"])
    ap.add_argument("--dir", required=True, help="Terraform root module directory (for example ../live/dev/web-db-manual)")
    ap.add_argument("--blueprint", default="web-db@1.0.0")
    ap.add_argument("--profile", default="infraflow")
    ap.add_argument("--region", default="ap-southeast-1")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    ap.add_argument("--no-backup", action="store_true", help="reclaimed: do not keep a final backup")
    args = ap.parse_args(argv)

    os.environ.setdefault("AWS_PROFILE", args.profile)
    os.environ.setdefault("AWS_DEFAULT_REGION", args.region)
    dir_ = Path(args.dir).resolve()
    base = load_env(dir_)
    env_id = base["env_id"]

    cat = load_from_repo(REPO)
    graph = build_graph(cat, args.blueprint)
    state_file = dir_ / ".infraflow-local.json"
    local = json.loads(state_file.read_text()) if state_file.exists() else {"dns": "SLEEP", "snapshots": {}}

    ctx = {"environment_id": env_id, "name_prefix": base["name_prefix"], "host": env_id,
           "operation_id": "local-" + hashlib.sha1(os.urandom(8)).hexdigest()[:8], "snapshots": local["snapshots"]}
    sigma = observe(graph, ctx)
    print("Observed state:")
    for u in graph.order:
        print(f"  {u:<9} {sigma[u]}")
    print(f"  dns       {local['dns']}")
    if args.cmd == "status":
        return 0
    if not args.level:
        ap.error("go requires a target level")

    p = planner.plan(graph, sigma, args.level, local["dns"], keep_final_backup=not args.no_backup)
    mc = checker.check_plan(graph, make_state(graph, sigma, local["dns"], local["dns"] == "APP"), p, allow_unsafe_start=True)
    print(f"\nModel checking: {'PASS' if mc['passed'] else 'FAIL'} ({mc['states_explored']} states)")
    if not mc["passed"]:
        print(json.dumps(mc["violation"], ensure_ascii=False, indent=2))
        return 1
    if planner.is_noop(p):
        print("Already at the target level; nothing to do.")
        return 0
    lease = {"app": {}, "parameters": {"size": base.get("size", "small")}}
    controller.attach_vars(graph, p, lease, {"environment_id": env_id, "name_prefix": base["name_prefix"],
                                             "snapshots": local["snapshots"]})
    print("\nPlan:")
    for s in p["pre"]:
        print(f"  pre     {s['action']} {s.get('value', s.get('seconds', ''))}")
    for st in p["stages"]:
        tfp = st["terraform"]
        print(f"  {st['name']:<16} terraform={tfp['set'] if tfp else '-'} drivers={[d['action'] + ':' + d['instance'] for d in st['drivers']]}")
    if p["health"]:
        print("  health  elbv2.target_healthy")
    for s in p["post"]:
        print(f"  post    dns -> {s['value']}")
    if not args.yes and input("\nApply? (yes/no) ").strip() != "yes":
        return 1

    store = MemoryStore()
    set_store(store)
    store.put_env({"environment_id": env_id, "lease_id": "local", "org_id": "local", "dns": local["dns"]})
    store.put_op({"operation_id": ctx["operation_id"], "environment_id": env_id, "requested_at": "-"})

    def run_driver(action):
        print(f"  -> driver {action['driver']} {action.get('instance', '')}")
        res = drivers.ACTIONS[action["driver"]](ctx, action)
        print(f"     {res}")
        return res

    for s in p["pre"]:
        run_driver(s)
        if s["action"] == "dns":
            local["dns"] = s["value"]
    tf(dir_, "init", "-input=false")
    for st in p["stages"]:
        print(f"\n== {st['name']}")
        t = st["terraform"]
        if t:
            (dir_ / "stage.auto.tfvars.json").write_text(json.dumps(t["vars"], indent=2))
            extra = ["-destroy"] if t["mode"] == "destroy" else []
            tf(dir_, "plan", "-input=false", "-out=plan.out", *extra)
            plan_json = json.loads(tf(dir_, "show", "-json", "plan.out", capture=True))
            snaps = sorted((store.get_op(ctx["operation_id"]) or {}).get("snapshots") or {})
            res = validator.validate(plan_json, cat, args.blueprint, env_id=env_id,
                                     allowed_instances=t["allowed_instances"], snapshots_ok=snaps,
                                     allow_data_loss=bool(p.get("allow_data_loss")))
            print(f"  Plan Validator: {'PASS' if res['passed'] else 'REJECTED'}")
            if not res["passed"]:
                print(json.dumps(res["violations"], ensure_ascii=False, indent=2))
                return 2
            tf(dir_, "apply", "-input=false", "plan.out")
        for d in st["drivers"]:
            r = run_driver(d)
            if r.get("snapshot_id"):
                local["snapshots"][d["instance"]] = r["snapshot_id"]
        state_file.write_text(json.dumps(local, indent=2))
    for s in p["health"]:
        run_driver(s)
    for s in p["post"]:
        run_driver(s)
        local["dns"] = s["value"]
    state_file.write_text(json.dumps(local, indent=2))
    env = store.get_env(env_id)
    print("\nDone.", f"Application: {env.get('app_url')}" if env.get("app_url") else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
