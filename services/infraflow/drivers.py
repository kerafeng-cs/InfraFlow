"""Driver Registry (TD mục 4.6): tập ĐÓNG các hành động AWS do InfraFlow viết.

Component không được định nghĩa driver mới; đây là ranh giới bảo mật.
Mọi driver idempotent (P5): gọi lại khi đã ở trạng thái đích thì trả NOOP.

Tìm tài nguyên theo quy ước tên `<name_prefix>-<hậu tố>` mà component đặt, cộng tag env_id.
Lambda tối đa 15 phút nên các vòng chờ dừng ở ~13 phút; quá thì báo lỗi để executor xử lý.
"""

from __future__ import annotations

import os
import time

from .ics.model import ABSENT, PRESENT, RUNNING, SNAPSHOTTED, STOPPED

_CLIENTS: dict = {}
SLEEP = time.sleep
MAX_WAIT_S = int(os.environ.get("DRIVER_MAX_WAIT_S", "780"))


class DriverError(Exception):
    pass


def aws(service: str):
    if service not in _CLIENTS:
        import boto3
        _CLIENTS[service] = boto3.client(service)
    return _CLIENTS[service]


def set_clients(clients: dict):
    _CLIENTS.clear()
    _CLIENTS.update(clients)


def _poll(fn, ok, what: str, interval: int = 15, max_wait: int | None = None):
    deadline = time.time() + (max_wait or MAX_WAIT_S)
    while True:
        v = fn()
        if ok(v):
            return v
        if time.time() > deadline:
            raise DriverError(f"quá thời gian chờ {what} (trạng thái cuối: {v})")
        SLEEP(interval)


def _env_filter(ctx):
    return [{"Name": "tag:infraflow:env_id", "Values": [ctx["environment_id"]]}]


# ---------------------------------------------------------------------------
# observe
# ---------------------------------------------------------------------------

def vpc_describe(ctx) -> str:
    r = aws("ec2").describe_vpcs(Filters=_env_filter(ctx) + [{"Name": "tag:Name", "Values": [f"{ctx['name_prefix']}-vpc"]}])
    return PRESENT if r["Vpcs"] else ABSENT


def nat_describe(ctx) -> str:
    r = aws("ec2").describe_nat_gateways(Filters=_env_filter(ctx) + [
        {"Name": "tag:Name", "Values": [f"{ctx['name_prefix']}-nat"]},
        {"Name": "state", "Values": ["pending", "available"]}])
    return PRESENT if r["NatGateways"] else ABSENT


def _ec2_instance(ctx):
    r = aws("ec2").describe_instances(Filters=_env_filter(ctx) + [
        {"Name": "tag:Name", "Values": [f"{ctx['name_prefix']}-app"]},
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}])
    for res in r["Reservations"]:
        for i in res["Instances"]:
            return i
    return None


def ec2_describe(ctx) -> str:
    i = _ec2_instance(ctx)
    if i is None:
        return ABSENT
    return RUNNING if i["State"]["Name"] in ("pending", "running") else STOPPED


def _rds(ctx):
    try:
        r = aws("rds").describe_db_instances(DBInstanceIdentifier=f"{ctx['name_prefix']}-db")
        return r["DBInstances"][0]
    except aws("rds").exceptions.DBInstanceNotFoundFault:
        return None


def rds_describe(ctx) -> str:
    db = _rds(ctx)
    if db is None:
        return SNAPSHOTTED if (ctx.get("snapshots") or {}).get("database") else ABSENT
    st = db["DBInstanceStatus"]
    if st in ("stopped", "stopping"):
        return STOPPED
    return RUNNING


def _lb(ctx):
    try:
        r = aws("elbv2").describe_load_balancers(Names=[f"{ctx['name_prefix']}-alb"])
        return r["LoadBalancers"][0]
    except aws("elbv2").exceptions.LoadBalancerNotFoundException:
        return None


def elbv2_describe(ctx) -> str:
    return PRESENT if _lb(ctx) else ABSENT


OBSERVE = {
    "vpc.describe": vpc_describe,
    "nat_gateway.describe": nat_describe,
    "ec2_instance.describe": ec2_describe,
    "rds_instance.describe": rds_describe,
    "elbv2.describe": elbv2_describe,
}


def observe_all(graph, ctx) -> dict:
    out = {}
    for u in graph.order:
        d = graph.instances[u].drivers.get("observe")
        if d not in OBSERVE:
            raise DriverError(f"{u}: không có driver observe")
        out[u] = OBSERVE[d](ctx)
    return out


# ---------------------------------------------------------------------------
# hành động
# ---------------------------------------------------------------------------

def ec2_start(ctx, action):
    i = _ec2_instance(ctx)
    if i is None:
        raise DriverError("không tìm thấy EC2 của app")
    if i["State"]["Name"] in ("stopping",):
        _poll(lambda: _ec2_instance(ctx)["State"]["Name"], lambda s: s == "stopped", "EC2 stopped")
    if _ec2_instance(ctx)["State"]["Name"] != "running":
        aws("ec2").start_instances(InstanceIds=[i["InstanceId"]])
        _poll(lambda: _ec2_instance(ctx)["State"]["Name"], lambda s: s == "running", "EC2 running")
        return {"status": "DONE", "observed_state": RUNNING}
    return {"status": "NOOP", "observed_state": RUNNING}


def ec2_stop(ctx, action):
    i = _ec2_instance(ctx)
    if i is None:
        return {"status": "NOOP", "observed_state": ABSENT}
    if i["State"]["Name"] in ("running", "pending"):
        aws("ec2").stop_instances(InstanceIds=[i["InstanceId"]])
    elif i["State"]["Name"] == "stopped":
        return {"status": "NOOP", "observed_state": STOPPED}
    _poll(lambda: _ec2_instance(ctx)["State"]["Name"], lambda s: s == "stopped", "EC2 stopped")
    return {"status": "DONE", "observed_state": STOPPED}


def ec2_status_ok(ctx, action):
    i = _ec2_instance(ctx)
    if i is None:
        raise DriverError("không tìm thấy EC2 của app")

    def st():
        r = aws("ec2").describe_instance_status(InstanceIds=[i["InstanceId"]])
        s = r["InstanceStatuses"]
        return s[0]["InstanceStatus"]["Status"] if s else "pending"

    _poll(st, lambda s: s == "ok", "EC2 status ok")
    return {"status": "DONE"}


def rds_start(ctx, action):
    db = _rds(ctx)
    if db is None:
        raise DriverError("không tìm thấy RDS")
    ident = db["DBInstanceIdentifier"]
    if db["DBInstanceStatus"] == "stopping":
        _poll(lambda: _rds(ctx)["DBInstanceStatus"], lambda s: s == "stopped", "RDS stopped")
    if _rds(ctx)["DBInstanceStatus"] == "stopped":
        aws("rds").start_db_instance(DBInstanceIdentifier=ident)
        status = "DONE"
    else:
        status = "NOOP"
    _poll(lambda: _rds(ctx)["DBInstanceStatus"], lambda s: s == "available", "RDS available", interval=20)
    return {"status": status, "observed_state": RUNNING}


def rds_stop(ctx, action):
    db = _rds(ctx)
    if db is None:
        return {"status": "NOOP", "observed_state": ABSENT}
    ident = db["DBInstanceIdentifier"]
    st = db["DBInstanceStatus"]
    if st == "stopped":
        return {"status": "NOOP", "observed_state": STOPPED}
    if st != "available":
        _poll(lambda: _rds(ctx)["DBInstanceStatus"], lambda s: s in ("available", "stopped"), "RDS ổn định", interval=20)
    if _rds(ctx)["DBInstanceStatus"] == "available":
        aws("rds").stop_db_instance(DBInstanceIdentifier=ident)
    _poll(lambda: _rds(ctx)["DBInstanceStatus"], lambda s: s == "stopped", "RDS stopped", interval=20)
    return {"status": "DONE", "observed_state": STOPPED}


def rds_snapshot(ctx, action):
    """Snapshot rồi chờ `available` (TD mục 11.3). Ghi snapshot_id vào operation để Validator V3 thấy."""
    from .store import get_store

    db = _rds(ctx)
    if db is None:
        raise DriverError("không tìm thấy RDS để snapshot")
    snap_id = f"{ctx['name_prefix']}-{ctx['operation_id']}".lower().replace("_", "-")[:255]
    rds = aws("rds")
    try:
        rds.describe_db_snapshots(DBSnapshotIdentifier=snap_id)
        exists = True
    except rds.exceptions.DBSnapshotNotFoundFault:
        exists = False
    if not exists:
        if db["DBInstanceStatus"] not in ("available", "stopped"):
            _poll(lambda: _rds(ctx)["DBInstanceStatus"], lambda s: s in ("available", "stopped"), "RDS ổn định", interval=20)
        rds.create_db_snapshot(DBSnapshotIdentifier=snap_id, DBInstanceIdentifier=db["DBInstanceIdentifier"],
                               Tags=[{"Key": "infraflow:env_id", "Value": ctx["environment_id"]},
                                     {"Key": "infraflow:managed", "Value": "true"},
                                     {"Key": "infraflow:purpose", "Value": action.get("purpose", "hibernate")},
                                     {"Key": "infraflow:operation_id", "Value": ctx["operation_id"]}])
    _poll(lambda: rds.describe_db_snapshots(DBSnapshotIdentifier=snap_id)["DBSnapshots"][0]["Status"],
          lambda s: s == "available", "snapshot available", interval=20)
    store = get_store()
    op = store.get_op(ctx["operation_id"]) or {}
    snaps = dict(op.get("snapshots") or {})
    snaps[action["instance"]] = snap_id
    store.update_op(ctx["operation_id"], {"snapshots": snaps})
    return {"status": "DONE", "snapshot_id": snap_id}


def rds_available(ctx, action):
    _poll(lambda: (_rds(ctx) or {}).get("DBInstanceStatus"), lambda s: s == "available", "RDS available", interval=20)
    return {"status": "DONE"}


def elbv2_target_healthy(ctx, action):
    lb = _poll(lambda: _lb(ctx), lambda v: v is not None and v["State"]["Code"] == "active", "ALB active")
    elb = aws("elbv2")
    tg = elb.describe_target_groups(Names=[f"{ctx['name_prefix']}-tg"])["TargetGroups"][0]

    def health():
        r = elb.describe_target_health(TargetGroupArn=tg["TargetGroupArn"])["TargetHealthDescriptions"]
        return [t["TargetHealth"]["State"] for t in r]

    _poll(health, lambda s: bool(s) and all(x == "healthy" for x in s), "target healthy",
          interval=15, max_wait=min(int(action.get("timeout_s", 900)), MAX_WAIT_S))
    return {"status": "DONE", "dns_name": lb["DNSName"], "zone_id": lb["CanonicalHostedZoneId"]}


def dns_point(ctx, action):
    """DNS chỉ trỏ vào ứng dụng sau health gate (bất biến 3). Bản ghi wildcard luôn trỏ sleeping page,
    nên đi ngủ chỉ cần xóa bản ghi riêng. Chưa có hosted zone thì chỉ ghi trạng thái (sleeping page
    sẽ chuyển hướng tới địa chỉ ALB khi môi trường thức)."""
    from .store import get_store

    value = action["value"]
    zone = os.environ.get("HOSTED_ZONE_ID")
    domain = os.environ.get("DOMAIN")
    lb = _lb(ctx) if value == "APP" else None
    if value == "APP" and lb is None:
        raise DriverError("không có ALB để trỏ DNS vào")
    fqdn = f"{ctx['host']}.{domain}" if domain else None

    if zone and domain:
        r53 = aws("route53")
        if value == "APP":
            r53.change_resource_record_sets(HostedZoneId=zone, ChangeBatch={"Changes": [{
                "Action": "UPSERT", "ResourceRecordSet": {
                    "Name": fqdn, "Type": "A",
                    "AliasTarget": {"HostedZoneId": lb["CanonicalHostedZoneId"], "DNSName": lb["DNSName"],
                                    "EvaluateTargetHealth": False}}}]})
        else:
            recs = r53.list_resource_record_sets(HostedZoneId=zone, StartRecordName=fqdn, StartRecordType="A",
                                                 MaxItems="1")["ResourceRecordSets"]
            if recs and recs[0]["Name"].rstrip(".") == fqdn and recs[0]["Type"] == "A":
                r53.change_resource_record_sets(HostedZoneId=zone, ChangeBatch={"Changes": [
                    {"Action": "DELETE", "ResourceRecordSet": recs[0]}]})

    fields = {"dns": value}
    if value == "APP":
        fields["app_url"] = f"https://{fqdn}" if (zone and domain and os.environ.get("HTTPS") == "true") else \
            (f"http://{fqdn}" if zone and domain else f"http://{lb['DNSName']}")
    get_store().update_env(ctx["environment_id"], fields, remove=() if value == "APP" else ("app_url",))
    return {"status": "DONE", "dns": value}


def wait_seconds(ctx, action):
    SLEEP(min(int(action.get("seconds", 0)), 600))
    return {"status": "DONE"}


ACTIONS = {
    "ec2_instance.start": ec2_start,
    "ec2_instance.stop": ec2_stop,
    "ec2_instance.status_ok": ec2_status_ok,
    "rds_instance.start": rds_start,
    "rds_instance.stop": rds_stop,
    "rds_instance.snapshot": rds_snapshot,
    "rds_instance.available": rds_available,
    "elbv2.target_healthy": elbv2_target_healthy,
    "dns.point": dns_point,
    "wait.seconds": wait_seconds,
}


def handler(event, context=None):
    """Lambda driver runner. Vào: {"action": {...}, "ctx": {...}}. Lỗi thì ném ngoại lệ để Step Functions bắt."""
    action, ctx = event["action"], event["ctx"]
    fn = ACTIONS.get(action["driver"])
    if fn is None:
        raise DriverError(f"driver ngoài registry: {action['driver']}")
    res = fn(ctx, action)
    res["driver"] = action["driver"]
    res["instance"] = action.get("instance")
    return res
