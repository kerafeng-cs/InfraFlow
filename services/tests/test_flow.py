"""Luồng end-to-end không cần AWS: API -> controller -> (executor giả) -> finish."""
import json
import os
import unittest
from datetime import datetime, timedelta, timezone

from infraflow import api, controller, drivers
from infraflow.ics.model import build_graph
from infraflow.store import MemoryStore, set_store

T0 = datetime(2026, 11, 2, 2, 0, tzinfo=timezone.utc)  # 09:00 thứ Hai giờ VN


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
        self.world = {}  # trạng thái hạ tầng giả theo env

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
        body = {"name": "congtyb", "environments": ["dev", "qa"], "blueprint_ref": "web-db@1.0.0",
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

        # Trong giờ làm: desired AWAKE -> wake từ con số 0
        r = self.run_controller(env_id, op_id)
        self.assertEqual((r["result"], r["action"]), ("started", "WAKE"))
        ex = self.sfn.started[-1]
        self.assertEqual(ex["name"], op_id)
        stages = ex["input"]["plan"]["stages"]
        self.assertEqual(stages[0]["terraform"]["set"], {"network": True})
        self.assertEqual(stages[0]["terraform"]["vars"]["network_present"], True)
        self.assertEqual(stages[0]["terraform"]["vars"]["egress_present"], False)
        self.assertTrue(ex["input"]["plan"]["model_check"]["passed"])

        # Đang chạy: controller không khởi chạy thêm
        self.assertEqual(self.run_controller(env_id)["result"], "busy")
        # Thao tác tay ngược mục tiêu -> 409
        st, b = self.call("POST", f"/v1/environments/{env_id}/sleep", {}, key="s1")
        self.assertEqual((st, b["error"]["code"]), (409, "CONCURRENT_OPERATION"))
        # Cùng mục tiêu -> trả operation đang chạy
        st, b = self.call("POST", f"/v1/environments/{env_id}/wake", {}, key="w1")
        self.assertEqual((st, b["operation_id"], b["existing"]), (202, op_id, True))

        self.complete_last()
        env = self.store.get_env(env_id)
        self.assertEqual((env["actual"], env["status"]), ("AWAKE", "ACTIVE"))
        self.assertNotIn("active_operation_id", env)
        self.assertEqual(self.run_controller(env_id)["result"], "in_sync")

        # Public status khi thức
        st, b = self.call("GET", "/v1/public/status", query={"host": env_id})
        self.assertEqual((b["availability"], b["app_url"]), ("AWAKE", "http://alb.example"))
        self.assertNotIn("operation_id", json.dumps(b))

        # Ngủ tay -> deep
        st, b = self.call("POST", f"/v1/environments/{env_id}/sleep", {}, key="s2")
        self.assertEqual(st, 202)
        r = self.run_controller(env_id, b["operation_id"])
        self.assertEqual(r["action"], "SLEEP")
        p = self.sfn.started[-1]["input"]["plan"]
        self.assertEqual([s["action"] for s in p["pre"]], ["dns", "wait"])
        self.complete_last()
        self.assertEqual(self.store.get_env(env_id)["actual"], "ASLEEP:deep")

        # Sleeping page bấm thức
        st, b = self.call("POST", "/v1/public/wake", {"host": env_id})
        self.assertEqual(st, 202)
        st, b = self.call("POST", "/v1/public/wake", {"host": env_id})
        self.assertEqual(st, 429)  # giới hạn tần suất

        # Nhật ký trạng thái -> chi phí 3 kịch bản
        controller._NOW = T0 + timedelta(hours=5)
        st, b = self.call("GET", f"/v1/leases/{body['lease_id']}/cost")
        self.assertEqual(st, 200)
        tot = b["totals"]
        self.assertGreater(tot["always_on"], tot["infraflow"])

    def test_outside_schedule_only_prepares(self):
        controller._NOW = T0 + timedelta(hours=12)  # 21:00
        st, body = self.create()
        env_id, op_id = self.invoked[0]
        r = self.run_controller(env_id, op_id)
        self.assertEqual(r["action"], "PROVISION")
        self.assertEqual(self.sfn.started[-1]["input"]["plan"]["to"]["database"], "ABSENT")
        self.complete_last()
        self.assertEqual(self.store.get_env(env_id)["status"], "PREPARED")
        self.assertEqual(self.run_controller(env_id)["result"], "in_sync")  # PREPARED thỏa ASLEEP

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
        st, b = self.call("POST", f"/v1/admin/environments/{env_id}/resolve", {"action": "retry", "note": "đã sửa quota"}, admin=True)
        self.assertEqual(st, 200)
        self.assertFalse(self.store.get_env(env_id)["blocked"])

    def test_drift_is_corrected_by_reconcile(self):
        """Ai đó bật EC2 trên console khi môi trường đang ngủ -> vòng đối soát đưa về."""
        self.create()
        env_id, op_id = self.invoked[0]
        self.run_controller(env_id, op_id)
        self.complete_last()
        controller._NOW = T0 + timedelta(hours=12)  # ngoài giờ
        self.run_controller(env_id)
        self.complete_last()
        self.assertEqual(self.store.get_env(env_id)["actual"], "ASLEEP:deep")
        self.world[env_id]["app"] = "RUNNING"  # trôi lệch
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

    def test_validation_and_idempotency(self):
        st, b = self.create(name="X")
        self.assertEqual(st, 400)
        st, b = self.create(data_policy={})
        self.assertEqual(b["error"]["code"], "INVALID_REQUEST")
        st1, b1 = self.create()
        st2, b2 = self.create()
        self.assertEqual((st2, b2), (st1, b1))  # cùng Idempotency-Key, cùng nội dung
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
