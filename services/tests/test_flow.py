"""End-to-end flow without AWS: API -> controller -> (fake executor) -> finish."""
import json
import os
import unittest
from datetime import datetime, timedelta, timezone

from infraflow import api, controller, drivers
from infraflow.ics.model import build_graph
from infraflow.store import MemoryStore, set_store

T0 = datetime(2026, 11, 2, 2, 0, tzinfo=timezone.utc)  # 09:00 Monday local time


class FakeSFN:
    def __init__(self):
        self.started = []

    def start_execution(self, stateMachineArn, name, input):
        self.started.append({"name": name, "input": json.loads(input)})
        return {"executionArn": f"arn:exec:{name}"}

    def describe_execution(self, executionArn):
        return {"status": "FAILED"}


def ev(method, path, body=None, key="k1", query=None, org="org_a", admin=False):
    claims = {"sub": "u1", "custom:org_id": org}
    if admin:
        claims["cognito:groups"] = "[infraflow_admins]"
    return {"requestContext": {"http": {"method": method}, "authorizer": {"jwt": {"claims": claims}}},
            "rawPath": path, "headers": {"Idempotency-Key": key},
            "body": json.dumps(body) if body is not None else None, "queryStringParameters": query}


class Flow(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        set_store(self.store)
        self.sfn = FakeSFN()
        drivers.set_clients({"stepfunctions": self.sfn})
        os.environ["STATE_MACHINE_ARN"] = "arn:aws:states:ap-southeast-1:1:stateMachine:infraflow-lifecycle"
        controller._NOW = T0
        self.invoked = []
        api.INVOKE = lambda env_id, op_id: self.invoked.append((env_id, op_id))
        self.graph = build_graph(controller.catalog(), "web-db@1.0.0")
        self.world = {}  # fake infrastructure state per environment

    def tearDown(self):
        controller._NOW = None

    def call(self, *a, **kw):
        r = api.handler(ev(*a, **kw))
        return r["statusCode"], (json.loads(r["body"]) if r["body"] else None)

    def observe(self, env_id):
        return lambda graph, ctx: dict(self.world.get(env_id) or {u: "ABSENT" for u in graph.order})

    def run_controller(self, env_id, op_id=None):
        return controller.reconcile(env_id, trigger_op=op_id, observe=self.observe(env_id))

    def complete_last(self, status="SUCCEEDED"):
        ex = self.sfn.started[-1]
        p, ctx = ex["input"]["plan"], ex["input"]["ctx"]
        if status == "SUCCEEDED":
            self.world[ctx["environment_id"]] = dict(p["to"])
            if p["post"]:
                self.store.update_env(ctx["environment_id"], {"dns": "APP", "app_url": "http://alb.example"})
            elif p["pre"]:
                self.store.update_env(ctx["environment_id"], {"dns": "SLEEP"}, remove=("app_url",))
        return controller.finish({"operation_id": ctx["operation_id"], "status": status,
                                  "error": {"Error": "X", "Cause": "health"} if status != "SUCCEEDED" else None})

    def create(self, **over):
        body = {"name": "acme", "environments": ["dev", "qa"], "blueprint_ref": "web-db@1.0.0",
                "expires_at": "2027-01-01T00:00:00Z", "starts_at": "2026-11-01T00:00:00Z",
                "data_policy": {"keep_final_backup": True},
                "activity_policy": {"mode": "schedule", "utc_offset_minutes": 420,
                                    "schedule": {"days": [1, 2, 3, 4, 5], "start": "08:00", "end": "19:00"}}}
        body.update(over)
        return self.call("POST", "/v1/leases", body)

    # -----------------------------------------------------------------
    def test_full_cycle(self):
        st, body = self.create()
        self.assertEqual(st, 202)
        self.assertEqual(len(self.invoked), 2)
        env_id, op_id = self.invoked[0]

        # Working hours: desired AWAKE -> wake from nothing
        r = self.run_controller(env_id, op_id)
        self.assertEqual((r["result"], r["action"]), ("started", "WAKE"))
        ex = self.sfn.started[-1]
        self.assertEqual(ex["name"], op_id)
        stages = ex["input"]["plan"]["stages"]
        self.assertEqual(stages[0]["terraform"]["set"], {"network": True})
        self.assertEqual(stages[0]["terraform"]["vars"]["network_present"], True)
        self.assertEqual(stages[0]["terraform"]["vars"]["egress_present"], False)
        self.assertTrue(ex["input"]["plan"]["model_check"]["passed"])

        # Running: the controller does not start another operation
        self.assertEqual(self.run_controller(env_id)["result"], "busy")
        # Manual action with the opposite target -> 409
        st, b = self.call("POST", f"/v1/environments/{env_id}/sleep", {}, key="s1")
        self.assertEqual((st, b["error"]["code"]), (409, "CONCURRENT_OPERATION"))
        # Same target while running -> 409 as well; the console disables both actions during an operation
        st, b = self.call("POST", f"/v1/environments/{env_id}/wake", {}, key="w1")
        self.assertEqual((st, b["error"]["code"]), (409, "OPERATION_IN_PROGRESS"))

        self.complete_last()
        env = self.store.get_env(env_id)
        self.assertEqual((env["actual"], env["status"]), ("AWAKE", "ACTIVE"))
        self.assertNotIn("active_operation_id", env)
        self.assertEqual(self.run_controller(env_id)["result"], "in_sync")

        # Public status while awake
        st, b = self.call("GET", "/v1/public/status", query={"host": env_id})
        self.assertEqual((b["availability"], b["app_url"]), ("AWAKE", "http://alb.example"))
        self.assertNotIn("operation_id", json.dumps(b))

        # Manual sleep -> deep
        st, b = self.call("POST", f"/v1/environments/{env_id}/sleep", {}, key="s2")
        self.assertEqual(st, 202)
        r = self.run_controller(env_id, b["operation_id"])
        self.assertEqual(r["action"], "SLEEP")
        p = self.sfn.started[-1]["input"]["plan"]
        self.assertEqual([s["action"] for s in p["pre"]], ["dns", "wait"])
        self.complete_last()
        self.assertEqual(self.store.get_env(env_id)["actual"], "ASLEEP:deep")

        # Wake request from the sleeping page
        st, b = self.call("POST", "/v1/public/wake", {"host": env_id})
        self.assertEqual(st, 202)
        st, b = self.call("POST", "/v1/public/wake", {"host": env_id})
        self.assertEqual(st, 429)  # rate limited

        # Transition log -> three cost scenarios
        controller._NOW = T0 + timedelta(hours=5)
        st, b = self.call("GET", f"/v1/leases/{body['lease_id']}/cost")
        self.assertEqual(st, 200)
        tot = b["totals"]
        self.assertGreater(tot["always_on"], tot["infraflow"])

    def test_private_blueprint_has_no_public_url(self):
        st, body = self.create(name="jobs", environments=["dev"], blueprint_ref="worker-cache@1.0.0")
        self.assertEqual(st, 202)
        env_id, op_id = self.invoked[0]
        r = self.run_controller(env_id, op_id)
        self.assertEqual((r["result"], r["action"]), ("started", "WAKE"))
        plan = self.sfn.started[-1]["input"]["plan"]
        self.assertEqual((plan["pre"], plan["post"]), ([], []))
        self.assertEqual(set(plan["to"]), {"network", "egress", "cache", "app"})
        self.complete_last()
        st, env = self.call("GET", f"/v1/environments/{env_id}")
        self.assertEqual((env["actual"], env["exposure"], env["url"]), ("AWAKE", "none", None))
        st, b = self.call("GET", "/v1/public/status", query={"host": env_id})
        self.assertEqual(st, 404)
        st, b = self.call("POST", "/v1/public/wake", {"host": env_id})
        self.assertEqual(st, 404)
        # Cost uses the components of this Blueprint (Redis, no ALB)
        controller._NOW = T0 + timedelta(hours=3)
        st, b = self.call("GET", f"/v1/leases/{body['lease_id']}/cost")
        self.assertEqual(st, 200)
        self.assertGreater(b["totals"]["always_on"], 0)

    def test_catalog_lists_classification(self):
        st, b = self.call("GET", "/v1/catalog/blueprints")
        self.assertEqual(st, 200)
        by_ref = {i["ref"]: i["classification"] for i in b["items"]}
        self.assertEqual(by_ref["web-db@1.0.0"]["exposure"], "public")
        self.assertEqual(by_ref["worker-cache@1.0.0"]["data"], "ephemeral")
        self.assertEqual(by_ref["web-only@1.0.0"]["data"], "stateless")

    def test_outside_schedule_only_prepares(self):
        controller._NOW = T0 + timedelta(hours=12)  # 21:00
        st, body = self.create()
        env_id, op_id = self.invoked[0]
        r = self.run_controller(env_id, op_id)
        self.assertEqual(r["action"], "PROVISION")
        self.assertEqual(self.sfn.started[-1]["input"]["plan"]["to"]["database"], "ABSENT")
        self.complete_last()
        self.assertEqual(self.store.get_env(env_id)["status"], "PREPARED")
        self.assertEqual(self.run_controller(env_id)["result"], "in_sync")  # PREPARED satisfies ASLEEP

    def test_health_failure_puts_back_to_sleep(self):
        self.create()
        env_id, op_id = self.invoked[0]
        self.run_controller(env_id, op_id)
        self.complete_last("FAILED")
        env = self.store.get_env(env_id)
        self.assertEqual(env["override"]["value"], "ASLEEP:deep")
        self.assertEqual(self.store.get_op(op_id)["error"]["code"], "HEALTH_GATE_FAILED")
        self.assertFalse(env.get("blocked"))

    def test_execution_error_blocks(self):
        self.create()
        env_id, op_id = self.invoked[0]
        self.run_controller(env_id, op_id)
        controller.finish({"operation_id": op_id, "status": "BLOCKED", "error": {"Error": "States.TaskFailed", "Cause": "terraform"}})
        env = self.store.get_env(env_id)
        self.assertTrue(env["blocked"])
        st, b = self.call("POST", f"/v1/environments/{env_id}/wake", {}, key="w9")
        self.assertEqual(b["error"]["code"], "ENVIRONMENT_BLOCKED")
        st, b = self.call("GET", "/v1/admin/blocked", admin=True)
        self.assertEqual(len(b["items"]), 1)
        st, b = self.call("POST", f"/v1/admin/environments/{env_id}/resolve", {"action": "retry", "note": "quota fixed"}, admin=True)
        self.assertEqual(st, 200)
        self.assertFalse(self.store.get_env(env_id)["blocked"])

    def test_drift_is_corrected_by_reconcile(self):
        """An instance started from the console while the environment sleeps is put back by reconciliation."""
        self.create()
        env_id, op_id = self.invoked[0]
        self.run_controller(env_id, op_id)
        self.complete_last()
        controller._NOW = T0 + timedelta(hours=12)  # outside working hours
        self.run_controller(env_id)
        self.complete_last()
        self.assertEqual(self.store.get_env(env_id)["actual"], "ASLEEP:deep")
        self.world[env_id]["app"] = "RUNNING"  # drift
        r = self.run_controller(env_id)
        self.assertEqual(r["action"], "SLEEP")
        p = self.sfn.started[-1]["input"]["plan"]
        self.assertEqual([d["action"] + ":" + d["instance"] for s in p["stages"] for d in s["drivers"]], ["stop:app"])

    def test_expiry_reclaims_and_verifies(self):
        self.create()
        env_id, op_id = self.invoked[0]
        self.run_controller(env_id, op_id)
        self.complete_last()
        controller._NOW = datetime(2027, 1, 2, tzinfo=timezone.utc)
        r = self.run_controller(env_id)
        self.assertEqual(r["action"], "RECLAIM")
        p = self.sfn.started[-1]["input"]["plan"]
        self.assertEqual(p["stages"][-1]["terraform"]["mode"], "destroy")
        self.assertIn("snapshot", [d["action"] for s in p["stages"] for d in s["drivers"]])
        self.complete_last()
        self.assertEqual(self.store.get_env(env_id)["status"], "VERIFYING")

        class Tagging:
            left = ["arn:aws:ec2:x:1:natgateway/nat-1"]

            def get_resources(self, **kw):
                return {"ResourceTagMappingList": [{"ResourceARN": a, "Tags": []} for a in self.left]}

        tg = Tagging()
        drivers.set_clients({"stepfunctions": self.sfn, "resourcegroupstaggingapi": tg})
        self.assertEqual(self.run_controller(env_id)["result"], "verifying")
        tg.left = []
        self.assertEqual(self.run_controller(env_id)["result"], "reclaimed")
        self.assertEqual(self.store.get_env(env_id)["status"], "RECLAIMED")

    def _reclaimed_with_leftovers(self, left):
        self.create()
        env_id, op_id = self.invoked[0]
        self.run_controller(env_id, op_id)
        self.complete_last()
        controller._NOW = datetime(2027, 1, 2, tzinfo=timezone.utc)
        self.run_controller(env_id)
        self.complete_last()

        class Tagging:
            def get_resources(self, **kw):
                return {"ResourceTagMappingList": [{"ResourceARN": a, "Tags": []} for a in left]}

        drivers.set_clients({"stepfunctions": self.sfn, "resourcegroupstaggingapi": Tagging()})
        return env_id

    def test_verify_blocks_when_resources_remain(self):
        env_id = self._reclaimed_with_leftovers(["arn:aws:ec2:x:1:natgateway/nat-1"])
        results = [self.run_controller(env_id)["result"] for _ in range(controller.VERIFY_MAX_ATTEMPTS)]
        self.assertEqual(results[:-1], ["verifying"] * (controller.VERIFY_MAX_ATTEMPTS - 1))
        self.assertEqual(results[-1], "blocked")
        env = self.store.get_env(env_id)
        self.assertEqual(env["blocked_reason"]["code"], "VERIFY_FAILED")
        self.assertNotEqual(env.get("status"), "RECLAIMED")

    def test_operation_past_deadline_blocks_with_unknown_outcome(self):
        self.create()
        env_id, op_id = self.invoked[0]
        self.run_controller(env_id, op_id)
        self.assertEqual(self.run_controller(env_id)["result"], "busy")
        controller._NOW = T0 + timedelta(minutes=controller.OP_TIMEOUT["WAKE"] + 1)
        r = self.run_controller(env_id)
        self.assertEqual((r["result"], r["code"]), ("blocked", "UNKNOWN_OUTCOME"))

    def test_extend_rejected_once_reclaim_started(self):
        st, b = self.create()
        lease = self.store.get_lease(b["lease_id"])
        controller._NOW = datetime(2027, 1, 2, tzinfo=timezone.utc)
        st, body = self.call("POST", f"/v1/leases/{b['lease_id']}/extend",
                             {"expires_at": "2027-02-01T00:00:00Z", "version": lease["version"]}, key="k-ext")
        self.assertEqual((st, body["error"]["code"]), (409, "LEASE_EXPIRED"))

    def test_extend_is_bounded_by_the_maximum_duration(self):
        st, b = self.create()
        lease = self.store.get_lease(b["lease_id"])
        st, body = self.call("POST", f"/v1/leases/{b['lease_id']}/extend",
                             {"expires_at": "2027-03-15T00:00:00Z", "version": lease["version"]}, key="k-long")
        self.assertEqual((st, body["error"]["code"]), (400, "ORG_LIMIT_EXCEEDED"))
        st, body = self.call("POST", f"/v1/leases/{b['lease_id']}/extend",
                             {"expires_at": "2027-02-01T00:00:00Z", "version": lease["version"]}, key="k-ok")
        self.assertEqual(st, 200)

    def _awake_env(self):
        self.create()
        env_id, op_id = self.invoked[0]
        self.run_controller(env_id, op_id)
        self.complete_last()
        return env_id

    def test_actions_follow_the_state(self):
        env_id = self._awake_env()
        st, env = self.call("GET", f"/v1/environments/{env_id}")
        self.assertEqual(env["actions"]["wake"], {"allowed": False, "reason": "ALREADY_AT_TARGET"})
        self.assertTrue(env["actions"]["sleep"]["allowed"])
        # Wake while awake is rejected, not turned into an empty operation
        st, b = self.call("POST", f"/v1/environments/{env_id}/wake", {}, key="w-awake")
        self.assertEqual((st, b["error"]["code"]), (409, "ALREADY_AT_TARGET"))

        st, b = self.call("POST", f"/v1/environments/{env_id}/sleep", {}, key="s-1")
        self.assertEqual(st, 202)
        self.run_controller(env_id, b["operation_id"])
        # While going to sleep every action is unavailable, and the public page offers no Wake button
        st, env = self.call("GET", f"/v1/environments/{env_id}")
        self.assertEqual({k: v["reason"] for k, v in env["actions"].items()},
                         {"wake": "OPERATION_IN_PROGRESS", "sleep": "OPERATION_IN_PROGRESS", "hibernate": "OPERATION_IN_PROGRESS"})
        st, public = self.call("GET", "/v1/public/status", query={"host": env_id})
        self.assertEqual((public["availability"], public["can_wake"]), ("SLEEPING", False))
        st, b = self.call("POST", f"/v1/environments/{env_id}/wake", {}, key="w-during-sleep")
        self.assertEqual((st, b["error"]["code"]), (409, "CONCURRENT_OPERATION"))

        self.complete_last()
        st, env = self.call("GET", f"/v1/environments/{env_id}")
        self.assertEqual({k: v["allowed"] for k, v in env["actions"].items()}, {"wake": True, "sleep": False, "hibernate": True})
        st, b = self.call("POST", f"/v1/environments/{env_id}/sleep", {}, key="s-again")
        self.assertEqual((st, b["error"]["code"]), (409, "ALREADY_AT_TARGET"))
        st, public = self.call("GET", "/v1/public/status", query={"host": env_id})
        self.assertTrue(public["can_wake"])

    def test_request_pending_until_the_controller_starts_it(self):
        env_id = self._awake_env()
        st, b = self.call("POST", f"/v1/environments/{env_id}/sleep", {}, key="p-1")
        self.assertEqual(st, 202)
        # The controller has not run yet: no active operation, but the request is pending
        st, env = self.call("GET", f"/v1/environments/{env_id}")
        self.assertEqual((env["requested"], env["actions"]["sleep"]["reason"]), ("ASLEEP:deep", "REQUEST_PENDING"))
        st, b = self.call("POST", f"/v1/environments/{env_id}/sleep", {}, key="p-2")
        self.assertEqual((st, b["error"]["code"]), (409, "REQUEST_PENDING"))
        st, b = self.call("POST", f"/v1/environments/{env_id}/wake", {}, key="p-3")
        self.assertEqual(st, 409)

    def test_public_wake_while_waking_follows_the_same_operation(self):
        self.create()
        env_id, op_id = self.invoked[0]
        self.run_controller(env_id, op_id)
        r = api.handler({"requestContext": {"http": {"method": "POST"}}, "rawPath": "/v1/public/wake",
                         "headers": {}, "body": json.dumps({"host": env_id})})
        self.assertEqual(r["statusCode"], 202)
        self.assertEqual(len(self.sfn.started), 1)

    def test_activity_policy_is_reduced_to_the_fields_of_its_mode(self):
        st, b = self.create(activity_policy={"mode": "on_demand", "idle_timeout_minutes": 30,
                                             "schedule": {"days": [1], "start": "08:00", "end": "09:00"},
                                             "off_hours_level": "hibernate", "admin": True})
        self.assertEqual(st, 202)
        stored = self.store.get_lease(b["lease_id"])["activity_policy"]
        self.assertEqual(stored, {"mode": "on_demand", "utc_offset_minutes": 420, "idle_level": "deep",
                                  "manual_wake_hours": 2, "idle_timeout_minutes": 30})

    def test_activity_policy_rejects_malformed_values(self):
        bad = [
            {"mode": "on_demand"},
            {"mode": "on_demand", "idle_timeout_minutes": "30"},
            {"mode": "on_demand", "idle_timeout_minutes": 2},
            {"mode": "schedule", "schedule": {"days": [1], "start": "19:00", "end": "08:00"}},
            {"mode": "schedule", "schedule": {"days": [8], "start": "08:00", "end": "19:00"}},
            {"mode": "schedule", "schedule": {"days": [1, 1], "start": "08:00", "end": "19:00"}},
            {"mode": "schedule", "schedule": {"days": [1], "start": "8:00", "end": "19:00"}},
            {"mode": "always"},
        ]
        for i, policy in enumerate(bad):
            st, b = self.call("POST", "/v1/leases", {"name": f"bad{i}", "environments": ["qa"], "blueprint_ref": "web-db@1.0.0",
                                                     "expires_at": "2027-01-01T00:00:00Z", "starts_at": "2026-11-01T00:00:00Z",
                                                     "data_policy": {"keep_final_backup": True}, "activity_policy": policy},
                              key=f"bad-{i}")
            self.assertEqual((st, b["error"]["code"]), (400, "INVALID_REQUEST"), policy)

    def test_validation_and_idempotency(self):
        st, b = self.create(name="X")
        self.assertEqual(st, 400)
        st, b = self.create(data_policy={})
        self.assertEqual(b["error"]["code"], "INVALID_REQUEST")
        st1, b1 = self.create()
        st2, b2 = self.create()
        self.assertEqual((st2, b2), (st1, b1))  # same Idempotency-Key, same body
        st3, b3 = self.create(environments=["uat"])
        self.assertEqual(b3["error"]["code"], "IDEMPOTENCY_KEY_REUSED")

    def test_org_isolation(self):
        st, b = self.create()
        st, other = self.call("GET", f"/v1/leases/{b['lease_id']}", org="org_khac")
        self.assertEqual(st, 404)
        st, lst = self.call("GET", "/v1/leases", org="org_khac")
        self.assertEqual(lst["items"], [])

    def test_compose_validate_endpoint(self):
        bp = controller.catalog().blueprint("web-db@1.0.0")
        st, b = self.call("POST", "/v1/blueprints/validate", bp)
        self.assertTrue(b["passed"])
        broken = json.loads(json.dumps(bp))
        broken["bindings"] = [x for x in broken["bindings"] if x["from"] != "app.db"]
        st, b = self.call("POST", "/v1/blueprints/validate", broken)
        self.assertFalse(b["passed"])
        self.assertEqual(b["composition"][0]["code"], "C1")


if __name__ == "__main__":
    unittest.main()
