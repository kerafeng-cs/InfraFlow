import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from infraflow.ics import checker, compiler, planner, static, validator
from infraflow.ics.catalog import load_bundle, load_from_repo
from infraflow.ics.model import (ABSENT, APP, RUNNING, SLEEP, STOPPED, build_graph, make_state, violations)

ROOT = Path(__file__).resolve().parents[2]
CAT = load_from_repo(ROOT)
G = build_graph(CAT, "web-db@1.0.0")


class TestGraph(unittest.TestCase):
    def test_edges(self):
        self.assertIn(("app", "egress"), G.serving_edges)
        self.assertNotIn(("app", "egress"), G.present_edges)  # serving without inputs -> no presence requirement
        self.assertIn(("app", "database"), G.present_edges)   # serving with inputs -> must exist
        self.assertEqual(G.dns_target, "entry")
        self.assertEqual(G.depth(), {"network": 0, "egress": 1, "database": 1, "app": 2, "entry": 3})

    def test_levels_safe(self):
        for lv in G.supported_levels:
            self.assertEqual(violations(G, checker.level_state(G, lv)), [], lv)


class TestPlanner(unittest.TestCase):
    def test_wake_order_matches_design(self):
        p = planner.plan(G, G.level_vector("deep"), "awake")
        shape = [(st["terraform"]["set"] if st["terraform"] else None,
                  sorted(d["action"] + ":" + d["instance"] for d in st["drivers"])) for st in p["stages"]]
        self.assertEqual(shape, [({"egress": True}, ["start:database"]),
                                 (None, ["start:app"]),
                                 ({"entry": True}, [])])
        self.assertEqual(p["health"][0]["driver"], "elbv2.target_healthy")
        self.assertEqual(p["post"][0]["value"], APP)

    def test_sleep_order_matches_design(self):
        p = planner.plan(G, G.level_vector("awake"), "deep", APP)
        self.assertEqual([s["action"] for s in p["pre"]], ["dns", "wait"])
        shape = [(st["terraform"]["set"] if st["terraform"] else None,
                  sorted(d["action"] + ":" + d["instance"] for d in st["drivers"])) for st in p["stages"]]
        self.assertEqual(shape, [({"entry": False}, []),
                                 (None, ["stop:app"]),
                                 ({"egress": False}, ["stop:database"])])

    def test_terraform_vars_full_vector(self):
        p = planner.plan(G, G.level_vector("deep"), "awake")
        last = p["stages"][-1]["terraform"]
        self.assertEqual(last["presence"], {u: True for u in G.order})
        self.assertEqual(last["allowed_instances"], ["entry"])

    def test_hibernate_snapshots_before_delete(self):
        p = planner.plan(G, G.level_vector("deep"), "hibernate")
        names = [s["name"] for s in p["stages"]]
        i_snap = names.index("down-1-snapshot")
        i_del = names.index("down-1")
        self.assertLess(i_snap, i_del)
        self.assertEqual(p["stages"][i_del]["terraform"]["set"], {"database": False})

    def test_prepared_satisfies_sleep(self):
        self.assertTrue(G.satisfies_sleep(G.level_vector("prepared"), "deep"))
        p = planner.plan(G, G.level_vector("prepared"), "deep")
        self.assertTrue(planner.is_noop(p))

    def test_noop_when_awake(self):
        p = planner.plan(G, G.level_vector("awake"), "awake", APP)
        self.assertTrue(planner.is_noop(p))


class TestModelChecker(unittest.TestCase):
    def test_web_db_passes_everything(self):
        rep = checker.check_blueprint(G)
        failed = [c for c in rep["checks"] if not c["passed"]]
        self.assertEqual(failed, [])
        self.assertTrue(any(c["code"] == "RESCUE" for c in rep["checks"]))

    def test_bad_plan_dns_before_health_is_caught(self):
        p = planner.plan(G, G.level_vector("deep"), "awake")
        p["post"], p["health"] = [], []
        p["pre"] = [{"action": "dns", "value": APP, "driver": "dns.point"}]
        r = checker.check_plan(G, make_state(G, G.level_vector("deep")), p)
        self.assertFalse(r["passed"])
        self.assertEqual(r["violation"]["rule"], "A3")
        self.assertTrue(r["violation"]["trace"])  # a counterexample is reported

    def test_bad_plan_delete_db_without_snapshot_is_caught(self):
        p = planner.plan(G, G.level_vector("deep"), "hibernate")
        p["stages"] = [s for s in p["stages"] if not s["name"].endswith("snapshot")]
        r = checker.check_plan(G, make_state(G, G.level_vector("deep")), p)
        self.assertFalse(r["passed"])
        self.assertEqual(r["violation"]["rule"], "A4")

    def test_bad_plan_wrong_order_is_caught(self):
        # Stopping the database before the app: some interleaving has the app serving while the database is not
        p = planner.plan(G, G.level_vector("awake"), "deep", APP)
        db_stage = p["stages"][2]
        app_stage = p["stages"][1]
        p["stages"] = [p["stages"][0], db_stage, app_stage]
        r = checker.check_plan(G, checker.level_state(G, "awake"), p)
        self.assertFalse(r["passed"])
        self.assertEqual(r["violation"]["rule"], "A2")

    def test_parallel_interleavings_explored(self):
        # Reclaim without backup: egress and database are removed in the SAME apply -> both orders must be explored
        p = planner.plan(G, G.level_vector("awake"), "reclaimed", APP, keep_final_backup=False)
        r = checker.check_plan(G, checker.level_state(G, "awake"), p)
        self.assertTrue(r["passed"], r.get("violation"))
        sigmas = {tuple(s.as_dict()[k] for k in ("egress", "database")) for s in r["reachable"]}
        self.assertIn(("ABSENT", "RUNNING"), sigmas)
        self.assertIn(("PRESENT", "ABSENT"), sigmas)

    def test_shallow_example_rejected(self):
        import yaml
        bp = yaml.safe_load((ROOT / "ics/examples/web-db-shallow.blueprint.yaml").read_text())
        g = build_graph(CAT, blueprint=bp)
        rep = checker.check_blueprint(g)
        self.assertFalse(rep["passed"])
        bad = [c for c in rep["checks"] if not c["passed"]][0]
        self.assertEqual((bad["code"], bad["detail"]["rule"]), ("C7", "A2"))


class TestStatic(unittest.TestCase):
    def test_components_pass(self):
        for ref, m in CAT.components.items():
            self.assertEqual(static.check_component(m, CAT.registry, ROOT / m["_dir"]), [], ref)

    def test_missing_binding_c1(self):
        import yaml
        bp = yaml.safe_load((ROOT / "ics/examples/web-only.blueprint.yaml").read_text())
        errs = static.check_composition(bp, CAT)
        self.assertEqual([e["code"] for e in errs], ["C1"])

    def test_dishonest_billing_class_s5(self):
        m = copy.deepcopy(CAT.component("aws-nat-egress@1.0.0"))
        m["component"]["billing_class"] = "free"
        m["lifecycle"]["levels"] = {"awake": "PRESENT", "deep": "PRESENT"}
        codes = {e["code"] for e in static.check_component(m, CAT.registry)}
        self.assertIn("S5", codes)

    def test_forbidden_construct(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            Path(d, "main.tf").write_text('resource "aws_eip" "x" {\n  provisioner "local-exec" {\n    command = "curl x"\n  }\n}\n')
            m = copy.deepcopy(CAT.component("aws-nat-egress@1.0.0"))
            m["component"]["resource_types"] = ["aws_eip"]
            codes = [e["code"] for e in static.check_component(m, CAT.registry, d)]
            self.assertIn("F", codes)


class TestCompiler(unittest.TestCase):
    def test_deterministic(self):
        a = compiler.compile_main(CAT, "web-db@1.0.0", "../../../components")
        b = compiler.compile_main(load_from_repo(ROOT), "web-db@1.0.0", "../../../components")
        self.assertEqual(a, b)

    def test_golden(self):
        golden = (ROOT / "live/dev/web-db-manual/main.tf").read_text()
        self.assertEqual(compiler.compile_main(CAT, "web-db@1.0.0", "../../../components"), golden)

    def test_bundle_equivalent(self):
        bundle = load_bundle(ROOT / "services/infraflow/catalog.json")
        self.assertEqual(compiler.compiled_hash(bundle, "web-db@1.0.0"), compiler.compiled_hash(CAT, "web-db@1.0.0"))

    def test_present_vars_have_no_default(self):
        text = compiler.compile_main(CAT, "web-db@1.0.0", "x")
        block = text.split('variable "database_present" {')[1].split("}")[0]
        self.assertNotIn("default", block)


def _rc(addr, rtype, actions, before=None, after=None):
    module = addr.rsplit(".", 2)[0]
    return {"address": addr, "module_address": module, "mode": "managed", "type": rtype,
            "change": {"actions": actions, "before": before, "after": after}}


TAGS = {"infraflow:managed": "true", "infraflow:env_id": "e1", "infraflow:lease_id": "l1", "infraflow:org_id": "o1"}


class TestValidator(unittest.TestCase):
    def run_v(self, rcs, **kw):
        args = dict(env_id="e1", allowed_instances=["entry"])
        args.update(kw)
        return validator.validate({"resource_changes": rcs}, CAT, "web-db@1.0.0", **args)

    def test_good_plan(self):
        r = self.run_v([_rc("module.entry[0].aws_lb.this", "aws_lb", ["create"], None, {"tags_all": TAGS})])
        self.assertTrue(r["passed"], r)

    def test_v2_instance_not_allowed(self):
        r = self.run_v([_rc("module.app[0].aws_instance.app", "aws_instance", ["update"], {"tags_all": TAGS}, {"tags_all": TAGS})])
        self.assertEqual([x["rule"] for x in r["violations"]], ["V2"])

    def test_v3_delete_db_without_snapshot(self):
        r = self.run_v([_rc("module.database[0].aws_db_instance.this", "aws_db_instance", ["delete"], {"tags_all": TAGS}, None)],
                       allowed_instances=["database"])
        self.assertEqual([x["rule"] for x in r["violations"]], ["V3"])
        r = self.run_v([_rc("module.database[0].aws_db_instance.this", "aws_db_instance", ["delete"], {"tags_all": TAGS}, None)],
                       allowed_instances=["database"], snapshots_ok=["database"])
        self.assertTrue(r["passed"])

    def test_v4_replace_db(self):
        r = self.run_v([_rc("module.database[0].aws_db_instance.this", "aws_db_instance", ["delete", "create"],
                            {"tags_all": TAGS}, {"tags_all": TAGS})], allowed_instances=["database"], snapshots_ok=["database"])
        self.assertEqual([x["rule"] for x in r["violations"]], ["V4"])

    def test_v5_v6_tags(self):
        r = self.run_v([_rc("module.entry[0].aws_lb.this", "aws_lb", ["create"], None, {"tags_all": {"x": "y"}})])
        self.assertIn("V5", [x["rule"] for x in r["violations"]])
        other = dict(TAGS, **{"infraflow:env_id": "khac"})
        r = self.run_v([_rc("module.entry[0].aws_lb.this", "aws_lb", ["delete"], {"tags_all": other}, None)])
        self.assertEqual([x["rule"] for x in r["violations"]], ["V6"])

    def test_v1_v8(self):
        r = self.run_v([_rc("aws_s3_bucket.x", "aws_s3_bucket", ["create"], None, {})])
        self.assertEqual([x["rule"] for x in r["violations"]], ["V1"])
        r = self.run_v([_rc("module.entry[0].aws_s3_bucket.x", "aws_s3_bucket", ["create"], None, {})])
        self.assertEqual([x["rule"] for x in r["violations"]], ["V8"])


if __name__ == "__main__":
    unittest.main()
