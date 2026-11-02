"""Chạy executor.asl.json bằng một trình thông dịch ASL rút gọn (Map/Choice/Task/Catch/Retry)
với plan thật do planner sinh, để bắt lỗi đường dẫn JSONPath, tham số CodeBuild, nhánh lỗi."""
import json
import re
import unittest
from pathlib import Path

from infraflow import controller
from infraflow.ics import planner
from infraflow.ics.model import build_graph

ASL = Path(__file__).resolve().parents[2] / "platform/executor.asl.json"


def get_path(data, path):
    if path == "$":
        return data
    cur = data
    for part in path[2:].split("."):
        cur = cur[part]
    return cur


def intrinsic(expr, data, ctx):
    m = re.fullmatch(r"States\.JsonToString\((.+)\)", expr)
    if m:
        return json.dumps(get_path(data, m.group(1)))
    m = re.fullmatch(r"States\.Format\('\{\}', (.+)\)", expr)
    if m:
        v = get_path(data, m.group(1))
        return "true" if v is True else "false" if v is False else str(v)
    if expr.startswith("$$."):
        return get_path(ctx, "$." + expr[3:])
    return get_path(data, expr)


def render(params, data, ctx):
    if isinstance(params, dict):
        out = {}
        for k, v in params.items():
            if k.endswith(".$"):
                out[k[:-2]] = intrinsic(v, data, ctx)
            else:
                out[k] = render(v, data, ctx)
        return out
    if isinstance(params, list):
        return [render(x, data, ctx) for x in params]
    return params


class TaskFailed(Exception):
    def __init__(self, error, cause):
        super().__init__(cause)
        self.error, self.cause = error, cause


class Machine:
    def __init__(self, defn, resources):
        self.defn, self.res = defn, resources

    def run(self, data, states=None, start=None, ctx=None):
        states = states or self.defn["States"]
        name = start or self.defn["StartAt"]
        ctx = ctx or {}
        while True:
            st = states[name]
            try:
                result = self.step(st, data, ctx)
            except TaskFailed as e:
                for c in st.get("Catch", []):
                    if "States.ALL" in c["ErrorEquals"] or e.error in c["ErrorEquals"]:
                        data = dict(data)
                        data[c["ResultPath"][2:]] = {"Error": e.error, "Cause": e.cause}
                        name = c["Next"]
                        break
                else:
                    raise
                continue
            rp = st.get("ResultPath", "$")
            if st["Type"] != "Choice":
                if rp is None:
                    pass
                elif rp == "$":
                    data = result
                else:
                    data = dict(data)
                    data[rp[2:]] = result
            nxt = result if st["Type"] == "Choice" else st.get("Next")
            if st.get("End") or nxt is None:
                return data
            name = nxt

    def step(self, st, data, ctx):
        t = st["Type"]
        if t == "Choice":
            for ch in st["Choices"]:
                v = get_path(data, ch["Variable"])
                if "IsNull" in ch and (v is None) == ch["IsNull"]:
                    return ch["Next"]
            return st["Default"]
        if t == "Map":
            items = get_path(data, st["ItemsPath"])
            proc = st["ItemProcessor"]
            out = []
            for i, item in enumerate(items):
                sel = render(st["ItemSelector"], data, {"Map": {"Item": {"Value": item, "Index": i}}})
                out.append(self.run(sel, proc["States"], proc["StartAt"]))
            return out
        if t == "Task":
            params = render(st["Parameters"], data, ctx)
            res = self.res[st["Resource"]](params)
            if "ResultSelector" in st:
                res = render(st["ResultSelector"], {"Payload": res}, ctx)
            return res
        raise NotImplementedError(t)


class TestExecutor(unittest.TestCase):
    def setUp(self):
        self.defn = json.loads(ASL.read_text())
        self.calls = []
        self.fail_driver = None

        def lam(params):
            p = params.get("Payload", {})
            self.calls.append(("lambda", params["FunctionName"], p))
            if params["FunctionName"] == "DRV" and p["action"]["driver"] == self.fail_driver:
                raise TaskFailed("DriverError", "timeout")
            return {"status": "DONE"}

        def cb(params):
            envs = {e["Name"]: e["Value"] for e in params["EnvironmentVariablesOverride"]}
            for v in envs.values():
                self.assertIsInstance(v, str)  # CodeBuild chỉ nhận chuỗi
            self.calls.append(("codebuild", params["ProjectName"], envs))
            return {}

        self.res = {"arn:aws:states:::lambda:invoke": lam, "arn:aws:states:::codebuild:startBuild.sync": cb}
        text = ASL.read_text().replace("${drivers_arn}", "DRV").replace("${controller_arn}", "CTL").replace("${codebuild_project}", "TF")
        self.m = Machine(json.loads(text), self.res)
        g = build_graph(controller.catalog(), "web-db@1.0.0")
        self.g = g
        lease = {"app": {}, "parameters": {"size": "small"}, "blueprint_ref": "web-db@1.0.0"}
        env = {"environment_id": "cty-qa", "name_prefix": "cty-qa", "lease_id": "l", "org_id": "o", "host": "cty-qa"}
        p = planner.plan(g, g.level_vector("deep"), "awake")
        controller.attach_vars(g, p, lease, env)
        ctx = controller.ctx_of(lease, env, "op_1")
        ctx["allow_data_loss"] = False
        self.input = {"ctx": ctx, "plan": p}

    def test_wake_runs_stages_in_order(self):
        self.m.run(self.input)
        seq = [(c[0], c[2]["action"]["driver"] if c[0] == "lambda" and "action" in c[2] else
                (c[2].get("mode") if c[0] == "lambda" else c[2]["ALLOWED_INSTANCES"])) for c in self.calls]
        self.assertEqual(seq, [("codebuild", '["egress"]'), ("lambda", "rds_instance.start"), ("lambda", "ec2_instance.start"),
                               ("codebuild", '["entry"]'), ("lambda", "elbv2.target_healthy"), ("lambda", "dns.point"),
                               ("lambda", "finish"), ("lambda", "single")])
        cb = self.calls[0][2]
        self.assertEqual(json.loads(cb["TF_VARS_JSON"])["egress_present"], True)
        self.assertEqual(cb["ALLOW_DATA_LOSS"], "false")
        self.assertEqual(cb["MODE"], "apply")
        finish = [c[2] for c in self.calls if c[0] == "lambda" and c[2].get("mode") == "finish"][0]
        self.assertEqual((finish["status"], finish["operation_id"]), ("SUCCEEDED", "op_1"))

    def test_health_failure_goes_to_failed(self):
        self.fail_driver = "elbv2.target_healthy"
        self.m.run(self.input)
        finish = [c[2] for c in self.calls if c[0] == "lambda" and c[2].get("mode") == "finish"][0]
        self.assertEqual(finish["status"], "FAILED")
        self.assertNotIn("dns.point", [c[2].get("action", {}).get("driver") for c in self.calls if c[0] == "lambda"])

    def test_stage_failure_blocks_and_skips_rest(self):
        self.fail_driver = "rds_instance.start"
        self.m.run(self.input)
        drivers = [c[2]["action"]["driver"] for c in self.calls if c[0] == "lambda" and "action" in c[2]]
        self.assertNotIn("ec2_instance.start", drivers)
        finish = [c[2] for c in self.calls if c[0] == "lambda" and c[2].get("mode") == "finish"][0]
        self.assertEqual(finish["status"], "BLOCKED")
        self.assertIn("timeout", finish["error"]["Cause"])


if __name__ == "__main__":
    unittest.main()
