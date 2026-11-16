import json
import unittest

from infraflow import report


def item(op_id, action, frm, to, status, start, end, error=None):
    it = {"operation_id": {"S": op_id}, "environment_id": {"S": "demo-dev"}, "action": {"S": action},
          "from_state": {"S": frm}, "target_level": {"S": to}, "status": {"S": status},
          "blueprint_ref": {"S": "web-db@1.1.0"}, "availability": {"S": "single"},
          "requested_at": {"S": start}, "started_at": {"S": start}, "finished_at": {"S": end}}
    if error:
        it["error"] = {"M": {"code": {"S": error}, "detail": {"S": "x"}}}
    return it


class TestReport(unittest.TestCase):
    def test_summary_groups_by_transition(self):
        items = [item("a", "WAKE", "ASLEEP:deep", "awake", "SUCCEEDED", "2026-11-15T01:00:00Z", "2026-11-15T01:04:00Z"),
                 item("b", "WAKE", "ASLEEP:deep", "awake", "SUCCEEDED", "2026-11-15T02:00:00Z", "2026-11-15T02:06:00Z"),
                 item("c", "RECLAIM", "ASLEEP:deep", "reclaimed", "BLOCKED", "2026-11-15T03:00:00Z",
                      "2026-11-15T03:02:00Z", "EXECUTION_FAILED"),
                 {"operation_id": {"S": "d"}, "action": {"S": "SLEEP"}, "status": {"S": "ACCEPTED"},
                  "requested_at": {"S": "2026-11-15T04:00:00Z"}}]
        rows = report.rows_of(items)
        self.assertEqual([r["action"] for r in rows], ["WAKE", "WAKE", "RECLAIM"])  # never started: left out
        s = {x["action"]: x for x in report.summary(rows)}
        self.assertEqual((s["WAKE"]["runs"], s["WAKE"]["median"], s["WAKE"]["min"], s["WAKE"]["max"]), (2, 300, 240, 360))
        self.assertEqual((s["RECLAIM"]["failed"], s["RECLAIM"]["errors"], s["RECLAIM"]["median"]), (1, "EXECUTION_FAILED", None))
        md = report.markdown(rows)
        self.assertIn("| web-db@1.1.0 | single | WAKE | ASLEEP:deep | awake | 2 | 2 | 0 | 5:00 | 4:00 | 6:00 | - |", md)

    def test_reads_an_aws_cli_export(self):
        import tempfile, io, contextlib
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"Items": [item("a", "SLEEP", "AWAKE", "deep", "SUCCEEDED",
                                      "2026-11-15T01:00:00Z", "2026-11-15T01:01:30Z")], "Count": 1}, f)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            report.main([f.name])
        self.assertIn("| SLEEP | AWAKE | deep | SUCCEEDED | 1:30 | 0:00 | - |", out.getvalue())
