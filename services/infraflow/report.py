"""Timing report of lifecycle operations, for slides and the final report.

Reads the operations table exported with the AWS CLI (DynamoDB JSON) and prints one row per
operation and a summary per transition. Standard library only, so it runs wherever the export
was made:

    aws dynamodb scan --profile infraflow --table-name infraflow-dev-operations \\
      --projection-expression "operation_id,environment_id,#a,target_level,from_state,blueprint_ref,availability,#s,requested_at,started_at,finished_at,#e" \\
      --expression-attribute-names '{"#a":"action","#s":"status","#e":"error"}' --output json > ops.json
    python3 -m infraflow.report ops.json               # Markdown
    python3 -m infraflow.report ops.json --csv out.csv # also every operation as CSV

Duration is from the start of execution to its end (`started_at` to `finished_at`). Queue is the
wait from the request to the start (`requested_at` to `started_at`).
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from datetime import datetime


def from_dynamo(value):
    """Converts one DynamoDB JSON value ({"S": ...}, {"M": ...}, ...) to Python."""
    (kind, v), = value.items()
    if kind == "S":
        return v
    if kind == "N":
        return float(v) if "." in v else int(v)
    if kind == "BOOL":
        return v
    if kind == "NULL":
        return None
    if kind == "M":
        return {k: from_dynamo(x) for k, x in v.items()}
    if kind == "L":
        return [from_dynamo(x) for x in v]
    return v


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _seconds(a, b):
    a, b = _ts(a), _ts(b)
    return round((b - a).total_seconds()) if a and b else None


def rows_of(items: list) -> list:
    rows = []
    for raw in items:
        op = {k: from_dynamo(v) for k, v in raw.items()}
        if not op.get("started_at"):
            continue  # never started: rejected, or answered as already at target
        error = op.get("error") or {}
        rows.append({
            "started_at": op["started_at"],
            "environment": op.get("environment_id", "-"),
            "blueprint": op.get("blueprint_ref", "-"),
            "availability": op.get("availability", "-"),
            "action": op.get("action", "-"),
            "from": op.get("from_state", "-"),
            "to": op.get("target_level", "-"),
            "status": op.get("status", "-"),
            "duration_s": _seconds(op.get("started_at"), op.get("finished_at")),
            "queue_s": _seconds(op.get("requested_at"), op.get("started_at")),
            "error": error.get("code", "") if isinstance(error, dict) else str(error),
        })
    return sorted(rows, key=lambda r: r["started_at"])


def _mmss(s):
    if s is None:
        return "-"
    s = int(s)
    return f"{s // 60}:{s % 60:02d}"


def summary(rows: list) -> list:
    groups: dict = {}
    for r in rows:
        key = (r["blueprint"], r["availability"], r["action"], r["from"], r["to"])
        groups.setdefault(key, []).append(r)
    out = []
    for key, rs in sorted(groups.items()):
        done = [r["duration_s"] for r in rs if r["status"] == "SUCCEEDED" and r["duration_s"] is not None]
        out.append({
            "blueprint": key[0], "availability": key[1], "action": key[2], "from": key[3], "to": key[4],
            "runs": len(rs),
            "succeeded": sum(1 for r in rs if r["status"] == "SUCCEEDED"),
            "failed": sum(1 for r in rs if r["status"] in ("FAILED", "BLOCKED", "TIMED_OUT")),
            "median": statistics.median(done) if done else None,
            "min": min(done) if done else None,
            "max": max(done) if done else None,
            "errors": ", ".join(sorted({r["error"] for r in rs if r["error"]})),
        })
    return out


def markdown(rows: list) -> str:
    lines = ["## Transitions", "",
             "| Blueprint | AZ | Action | From | To | Runs | OK | Failed | Median | Min | Max | Errors |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in summary(rows):
        lines.append(f"| {s['blueprint']} | {s['availability']} | {s['action']} | {s['from']} | {s['to']} | {s['runs']} "
                     f"| {s['succeeded']} | {s['failed']} | {_mmss(s['median'])} | {_mmss(s['min'])} | {_mmss(s['max'])} "
                     f"| {s['errors'] or '-'} |")
    lines += ["", "## Operations", "",
              "| Started (UTC) | Environment | Action | From | To | Status | Duration | Queue | Error |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['started_at'][:19].replace('T', ' ')} | {r['environment']} | {r['action']} | {r['from']} "
                     f"| {r['to']} | {r['status']} | {_mmss(r['duration_s'])} | {_mmss(r['queue_s'])} | {r['error'] or '-'} |")
    lines += ["", "Durations in minutes:seconds, from the start of execution to its end."]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Timing report of InfraFlow operations")
    ap.add_argument("export", help="output of aws dynamodb scan --output json")
    ap.add_argument("--csv", help="also write every operation to this CSV file")
    args = ap.parse_args(argv)
    with open(args.export, encoding="utf-8") as f:
        rows = rows_of(json.load(f).get("Items", []))
    print(markdown(rows))
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["started_at"])
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
