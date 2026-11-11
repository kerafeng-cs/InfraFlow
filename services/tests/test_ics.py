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

    def test_optional_port_may_stay_unbound_but_required_may_not(self):
        bp = copy.deepcopy(CAT.blueprint("web-db@1.0.0"))
        bp["instances"]["app"]["component"] = "aws-ec2-docker-app@1.1.0"
        bp["bindings"] = [b for b in bp["bindings"] if b["from"] != "app.db"]
        bp["instances"].pop("database")
        bp["bindings"] = [b for b in bp["bindings"] if not b["from"].startswith("database.")]
        self.assertEqual(static.check_composition(bp, CAT), [])
        bp["bindings"] = [b for b in bp["bindings"] if b["from"] != "app.egress"]
        self.assertEqual([e["code"] for e in static.check_composition(bp, CAT)], ["C1"])

    def test_optional_port_needs_enabled_variable(self):
        m = copy.deepcopy(CAT.component("aws-ec2-docker-app@1.1.0"))
        next(r for r in m["requires"] if r["port"] == "db").pop("enabled_variable")
        self.assertIn("S7", {e["code"] for e in static.check_component(m, CAT.registry)})

    def test_manifest_variables_must_exist_in_module(self):
        m = copy.deepcopy(CAT.component("aws-ec2-docker-app@1.1.0"))
        next(r for r in m["requires"] if r["port"] == "db")["enabled_variable"] = "database_on"
        errs = static.check_component(m, CAT.registry, ROOT / m["_dir"])
        self.assertTrue(any(e["code"] == "S7" and "database_on" in e["message"] for e in errs), errs)

    def test_cache_must_declare_ephemeral_data(self):
        m = copy.deepcopy(CAT.component("aws-elasticache-redis@1.0.0"))
        m["component"]["data_class"] = "none"
        self.assertIn("S5", {e["code"] for e in static.check_component(m, CAT.registry)})

    def test_exposure_controls_the_dns_binding(self):
        bp = copy.deepcopy(CAT.blueprint("worker-db@1.0.0"))
        self.assertEqual(static.check_composition(bp, CAT), [])
        bp["blueprint"]["exposure"] = "public"
        self.assertEqual([e["code"] for e in static.check_composition(bp, CAT)], ["C4"])

    def test_classification_category_is_checked(self):
        bp = copy.deepcopy(CAT.blueprint("web-only@1.0.0"))
        bp["blueprint"]["classification"]["category"] = "games"
        self.assertEqual([e["code"] for e in static.check_composition(bp, CAT)], ["M1"])

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


class TestCatalog(unittest.TestCase):
    def test_every_blueprint_passes_composition_and_model_checking(self):
        for ref, bp in CAT.blueprints.items():
            self.assertEqual(static.check_composition(bp, CAT), [], ref)
            rep = checker.check_blueprint(build_graph(CAT, ref))
            self.assertTrue(rep["passed"], (ref, [c for c in rep["checks"] if not c["passed"]]))

    def test_cache_without_ssm_endpoint_would_violate_a1(self):
        """The design flaw the checker found: an app that reads the cache address as an input
        keeps a present edge to a cache that is removed in deep sleep."""
        cat = copy.deepcopy(CAT)
        app = cat.components["aws-ec2-docker-app@1.1.0"]
        next(r for r in app["requires"] if r["port"] == "cache")["inputs"] = {"host": "cache_host"}
        rep = checker.check_blueprint(build_graph(cat, "web-db-cache@1.0.0"), recoverability=False)
        failed = [c for c in rep["checks"] if not c["passed"]]
        self.assertEqual((failed[0]["code"], failed[0]["detail"]["rule"]), ("C7", "A1"))

    def test_optional_ports_compile_to_flags(self):
        web_only = compiler.compile_main(CAT, "web-only@1.0.0", "../../../components")
        self.assertRegex(web_only, r"db_enabled += false")
        self.assertRegex(web_only, r"cache_enabled += false")
        self.assertIn("app.db not bound", web_only)
        self.assertNotIn("db_host", web_only)
        cached = compiler.compile_main(CAT, "web-db-cache@1.0.0", "../../../components")
        self.assertRegex(cached, r"db_enabled += true")
        self.assertRegex(cached, r"cache_enabled += true")
        self.assertRegex(cached, r"db_host += one\(module\.database\[\*\]\.endpoint_address\)")

    def test_every_blueprint_compiles(self):
        for ref in CAT.blueprints:
            src = compiler.compile_main(CAT, ref, "../../../components")
            self.assertIn("compiled_hash", src, ref)

    def test_queue_worker_wires_the_queue_and_keeps_it_while_asleep(self):
        src = compiler.compile_main(CAT, "queue-worker@1.0.0", "../../../components")
        self.assertRegex(src, r"queue_enabled += true")
        self.assertRegex(src, r"queue_url += one\(module\.queue\[\*\]\.queue_url\)")
        g = build_graph(CAT, "queue-worker@1.0.0")
        self.assertEqual(g.level_vector("hibernate")["queue"], "PRESENT")
        p = planner.plan(g, g.level_vector("awake"), "hibernate")
        self.assertEqual(p["to"]["queue"], "PRESENT")
        self.assertNotIn("queue", [u for st in p["stages"] if st["terraform"] for u in st["terraform"]["set"]])

    def test_ml_workbench_snapshots_the_volume_after_removing_the_workbench(self):
        g = build_graph(CAT, "ml-workbench@1.0.0")
        p = planner.plan(g, g.level_vector("awake"), "hibernate")
        names = [st["name"] for st in p["stages"]]
        sets = [st["terraform"]["set"] if st["terraform"] else {} for st in p["stages"]]
        removed_workbench = next(i for i, s in enumerate(sets) if s.get("workbench") is False)
        snapshot = next(i for i, st in enumerate(p["stages"]) if any(d["driver"] == "ebs_volume.snapshot" for d in st["drivers"]))
        removed_volume = next(i for i, s in enumerate(sets) if s.get("volume") is False)
        self.assertLess(removed_workbench, snapshot, names)
        self.assertLess(snapshot, removed_volume, names)
        self.assertEqual(p["to"]["volume"], "SNAPSHOTTED")
        # Waking restores the volume before the workbench attaches it
        back = planner.plan(g, p["to"], "awake")
        up = [st["terraform"] for st in back["stages"] if st["terraform"]]
        self.assertEqual(next(t["restore"] for t in up if "volume" in t["set"]), ["volume"])

    def test_web_ecs_creates_the_entry_before_the_service(self):
        g = build_graph(CAT, "web-ecs@1.0.0")
        self.assertIn(("service", "entry"), g.present_edges)
        p = planner.plan(g, g.level_vector("deep"), "awake")
        order = [u for st in p["stages"] if st["terraform"] for u in st["terraform"]["set"]]
        self.assertLess(order.index("entry"), order.index("service"))
        self.assertEqual((p["health"][0]["driver"], p["post"][0]["value"]), ("elbv2.target_healthy", "APP"))

    def test_private_blueprint_has_no_public_endpoint_or_dns_steps(self):
        self.assertNotIn("public_endpoint", compiler.compile_main(CAT, "worker-db@1.0.0", "../../../components"))
        g = build_graph(CAT, "worker-db@1.0.0")
        p = planner.plan(g, g.level_vector("deep"), "awake")
        self.assertEqual((p["post"], p["health"][0]["driver"]), ([], "wait.seconds"))


class TestClassification(unittest.TestCase):
    def test_derived_axes(self):
        from infraflow.classify import classify
        got = {r: classify(CAT, r) for r in CAT.blueprints}
        self.assertEqual({r: (c["category"], c["exposure"], c["data"]) for r, c in got.items()}, {
            "web-db@1.0.0": ("web", "public", "persistent"),
            "web-db-cache@1.0.0": ("web", "public", "persistent"),
            "web-only@1.0.0": ("web", "public", "stateless"),
            "worker-db@1.0.0": ("worker", "none", "persistent"),
            "worker-cache@1.0.0": ("worker", "none", "ephemeral"),
            "web-ecs@1.0.0": ("web", "public", "stateless"),
            "queue-worker@1.0.0": ("worker", "none", "retained"),
            "postgres-sandbox@1.0.0": ("data", "none", "persistent"),
            "search-sandbox@1.0.0": ("data", "none", "ephemeral"),
            "ml-workbench@1.0.0": ("ml", "none", "persistent"),
        })
        for r, c in got.items():
            small, medium = c["hourly_usd"]["small"], c["hourly_usd"]["medium"]
            self.assertGreater(small["awake"], small["deep"], r)
            self.assertGreaterEqual(small["deep"], small["hibernate"], r)
            self.assertGreater(medium["awake"], small["awake"], r)

    def test_price_model_follows_the_components(self):
        from infraflow.cost import PriceModel
        web_db = PriceModel(build_graph(CAT, "web-db@1.0.0"))
        cached = PriceModel(build_graph(CAT, "web-db-cache@1.0.0"))
        self.assertAlmostEqual(cached.level("awake") - web_db.level("awake"), 0.024, places=3)
        self.assertEqual(cached.level("deep"), web_db.level("deep"))  # the cache is removed in deep
        self.assertIn("cache", cached.rounded)
        self.assertNotIn("app", cached.rounded)


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
