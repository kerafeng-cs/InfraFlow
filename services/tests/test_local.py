import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from infraflow import drivers, local


class TestLocal(unittest.TestCase):
    def test_wake_from_deep_runs_plan(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "env.auto.tfvars.json").write_text(json.dumps({"name_prefix": "e1", "env_id": "e1"}))
            calls = []

            def fake_tf(dir_, *args, capture=False):
                calls.append(args[0])
                if capture:
                    return json.dumps({"resource_changes": []})

            done = []
            acts = {k: (lambda ctx, a, k=k: done.append(k) or {"status": "DONE"}) for k in drivers.ACTIONS}
            deep = {"network": "PRESENT", "egress": "ABSENT", "database": "STOPPED", "app": "STOPPED", "entry": "ABSENT"}
            with mock.patch.object(local, "tf", fake_tf), mock.patch.object(local, "observe", lambda g, c: dict(deep)), \
                    mock.patch.dict(drivers.ACTIONS, acts):
                rc = local.main(["go", "awake", "--dir", d, "--yes"])
            self.assertEqual(rc, 0)
            self.assertEqual(done, ["rds_instance.start", "ec2_instance.start", "elbv2.target_healthy", "dns.point"])
            self.assertEqual(calls.count("apply"), 2)
            stage_vars = json.loads(Path(d, "stage.auto.tfvars.json").read_text())
            self.assertTrue(stage_vars["entry_present"])
            self.assertEqual(json.loads(Path(d, ".infraflow-local.json").read_text())["dns"], "APP")


if __name__ == "__main__":
    unittest.main()
