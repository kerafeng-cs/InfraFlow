"""Driver Registry: the CLOSED set of AWS actions written by InfraFlow.

Components cannot define new drivers; this is a security boundary.
Every driver is idempotent: calling it again at the target state returns NOOP.

Resources are located by the `<name_prefix>-<suffix>` naming convention used by components,
together with the env_id tag. Lambda runs for at most 15 minutes, so wait loops stop at about
13 minutes and raise an error for the executor to handle.
"""

from __future__ import annotations

import os
import time
from functools import partial

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
            raise DriverError(f"timed out waiting for {what} (last state: {v})")
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


def _ec2_instance(ctx, role: str = "app"):
    """EC2 instances are named <name_prefix>-<role>: app, bastion or workbench."""
    r = aws("ec2").describe_instances(Filters=_env_filter(ctx) + [
        {"Name": "tag:Name", "Values": [f"{ctx['name_prefix']}-{role}"]},
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}])
    for res in r["Reservations"]:
        for i in res["Instances"]:
            return i
    return None


def ec2_describe(ctx, role: str = "app") -> str:
    i = _ec2_instance(ctx, role)
    if i is None:
        return ABSENT
    return RUNNING if i["State"]["Name"] in ("pending", "running") else STOPPED


def _rds(ctx):
    try:
        r = aws("rds").describe_db_instances(DBInstanceIdentifier=f"{ctx['name_prefix']}-db")
        return r["DBInstances"][0]
    except aws("rds").exceptions.DBInstanceNotFoundFault:
        return None


def _snapshotted_or_absent(ctx) -> str:
    """A data resource that does not exist is SNAPSHOTTED when the Environment holds its snapshot."""
    return SNAPSHOTTED if (ctx.get("snapshots") or {}).get(ctx.get("instance", "database")) else ABSENT


def rds_describe(ctx) -> str:
    db = _rds(ctx)
    if db is None:
        return _snapshotted_or_absent(ctx)
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


def elasticache_describe(ctx) -> str:
    """A cache node that is being deleted no longer serves and is counted as absent."""
    try:
        r = aws("elasticache").describe_cache_clusters(CacheClusterId=f"{ctx['name_prefix']}-redis")
    except aws("elasticache").exceptions.CacheClusterNotFoundFault:
        return ABSENT
    st = r["CacheClusters"][0]["CacheClusterStatus"]
    return ABSENT if st in ("deleting", "deleted") else PRESENT


def _volume(ctx):
    r = aws("ec2").describe_volumes(Filters=_env_filter(ctx) + [
        {"Name": "tag:Name", "Values": [f"{ctx['name_prefix']}-data"]},
        {"Name": "status", "Values": ["creating", "available", "in-use"]}])
    return r["Volumes"][0] if r["Volumes"] else None


def ebs_describe(ctx) -> str:
    return RUNNING if _volume(ctx) else _snapshotted_or_absent(ctx)


def _ecs_service(ctx):
    np = ctx["name_prefix"]
    ecs = aws("ecs")
    try:
        r = ecs.describe_services(cluster=f"{np}-cluster", services=[f"{np}-svc"])
    except ecs.exceptions.ClusterNotFoundException:
        return None
    svc = next((x for x in r["services"] if x["status"] == "ACTIVE"), None)
    return svc


def ecs_describe(ctx) -> str:
    svc = _ecs_service(ctx)
    if svc is None:
        return ABSENT
    return STOPPED if svc["desiredCount"] == 0 else RUNNING


def sqs_describe(ctx) -> str:
    sqs = aws("sqs")
    try:
        sqs.get_queue_url(QueueName=f"{ctx['name_prefix']}-queue")
    except sqs.exceptions.QueueDoesNotExist:
        return ABSENT
    return PRESENT


def opensearch_describe(ctx) -> str:
    """Matches the domain name of aws-opensearch-domain: <name_prefix>-search, at most 28 characters."""
    client = aws("opensearch")
    try:
        r = client.describe_domain(DomainName=f"{ctx['name_prefix']}-search"[:28])
    except client.exceptions.ResourceNotFoundException:
        return ABSENT
    return ABSENT if r["DomainStatus"].get("Deleted") else PRESENT


OBSERVE = {
    "vpc.describe": vpc_describe,
    "nat_gateway.describe": nat_describe,
    "ec2_instance.describe": ec2_describe,
    "ec2_bastion.describe": partial(ec2_describe, role="bastion"),
    "ec2_workbench.describe": partial(ec2_describe, role="workbench"),
    "rds_instance.describe": rds_describe,
    "ebs_volume.describe": ebs_describe,
    "elbv2.describe": elbv2_describe,
    "elasticache.describe": elasticache_describe,
    "ecs_service.describe": ecs_describe,
    "sqs.describe": sqs_describe,
    "opensearch.describe": opensearch_describe,
}


def observe_all(graph, ctx) -> dict:
    out = {}
    for u in graph.order:
        d = graph.instances[u].drivers.get("observe")
        if d not in OBSERVE:
            raise DriverError(f"{u}: no observe driver")
        out[u] = OBSERVE[d]({**ctx, "instance": u})
    return out


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------

def ec2_start(ctx, action, role: str = "app"):
    i = _ec2_instance(ctx, role)
    if i is None:
        raise DriverError(f"EC2 instance {role} not found")
    if i["State"]["Name"] in ("stopping",):
        _poll(lambda: _ec2_instance(ctx, role)["State"]["Name"], lambda s: s == "stopped", "EC2 stopped")
    if _ec2_instance(ctx, role)["State"]["Name"] != "running":
        aws("ec2").start_instances(InstanceIds=[i["InstanceId"]])
        _poll(lambda: _ec2_instance(ctx, role)["State"]["Name"], lambda s: s == "running", "EC2 running")
        return {"status": "DONE", "observed_state": RUNNING}
    return {"status": "NOOP", "observed_state": RUNNING}


def ec2_stop(ctx, action, role: str = "app"):
    i = _ec2_instance(ctx, role)
    if i is None:
        return {"status": "NOOP", "observed_state": ABSENT}
    if i["State"]["Name"] in ("running", "pending"):
        aws("ec2").stop_instances(InstanceIds=[i["InstanceId"]])
    elif i["State"]["Name"] == "stopped":
        return {"status": "NOOP", "observed_state": STOPPED}
    _poll(lambda: _ec2_instance(ctx, role)["State"]["Name"], lambda s: s == "stopped", "EC2 stopped")
    return {"status": "DONE", "observed_state": STOPPED}


def ec2_status_ok(ctx, action, role: str = "app"):
    i = _ec2_instance(ctx, role)
    if i is None:
        raise DriverError(f"EC2 instance {role} not found")

    def st():
        r = aws("ec2").describe_instance_status(InstanceIds=[i["InstanceId"]])
        s = r["InstanceStatuses"]
        return s[0]["InstanceStatus"]["Status"] if s else "pending"

    _poll(st, lambda s: s == "ok", "EC2 status ok")
    return {"status": "DONE"}


def rds_start(ctx, action):
    db = _rds(ctx)
    if db is None:
        raise DriverError("RDS instance not found")
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
        _poll(lambda: _rds(ctx)["DBInstanceStatus"], lambda s: s in ("available", "stopped"), "RDS to settle", interval=20)
    if _rds(ctx)["DBInstanceStatus"] == "available":
        aws("rds").stop_db_instance(DBInstanceIdentifier=ident)
    _poll(lambda: _rds(ctx)["DBInstanceStatus"], lambda s: s == "stopped", "RDS stopped", interval=20)
    return {"status": "DONE", "observed_state": STOPPED}


def rds_snapshot(ctx, action):
    """Takes a snapshot and waits until it is `available`. Records snapshot_id on the operation for Validator rule V3."""
    from .store import get_store

    db = _rds(ctx)
    if db is None:
        raise DriverError("RDS instance to snapshot not found")
    snap_id = f"{ctx['name_prefix']}-{ctx['operation_id']}".lower().replace("_", "-")[:255]
    rds = aws("rds")
    try:
        rds.describe_db_snapshots(DBSnapshotIdentifier=snap_id)
        exists = True
    except rds.exceptions.DBSnapshotNotFoundFault:
        exists = False
    if not exists:
        if db["DBInstanceStatus"] not in ("available", "stopped"):
            _poll(lambda: _rds(ctx)["DBInstanceStatus"], lambda s: s in ("available", "stopped"), "RDS to settle", interval=20)
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


def ebs_snapshot(ctx, action):
    """Snapshots the data volume and waits until the snapshot is `completed`. Idempotent per
    operation: a retry finds the snapshot by its operation tag. Records the id for rule V3."""
    from .store import get_store

    ec2 = aws("ec2")
    vol = _volume(ctx)
    if vol is None:
        raise DriverError("data volume to snapshot not found")

    def find():
        r = ec2.describe_snapshots(OwnerIds=["self"], Filters=_env_filter(ctx) + [
            {"Name": "tag:infraflow:operation_id", "Values": [ctx["operation_id"]]},
            {"Name": "volume-id", "Values": [vol["VolumeId"]]}])
        return r["Snapshots"][0] if r["Snapshots"] else None

    snap = find()
    if snap is None:
        snap = ec2.create_snapshot(VolumeId=vol["VolumeId"], Description=f"InfraFlow {ctx['name_prefix']} data",
                                   TagSpecifications=[{"ResourceType": "snapshot", "Tags": [
                                       {"Key": "Name", "Value": f"{ctx['name_prefix']}-data"},
                                       {"Key": "infraflow:env_id", "Value": ctx["environment_id"]},
                                       {"Key": "infraflow:managed", "Value": "true"},
                                       {"Key": "infraflow:purpose", "Value": action.get("purpose", "hibernate")},
                                       {"Key": "infraflow:operation_id", "Value": ctx["operation_id"]}]}])
    snap_id = snap["SnapshotId"]
    _poll(lambda: ec2.describe_snapshots(SnapshotIds=[snap_id])["Snapshots"][0]["State"],
          lambda s: s == "completed", "EBS snapshot completed", interval=20)
    store = get_store()
    op = store.get_op(ctx["operation_id"]) or {}
    snaps = dict(op.get("snapshots") or {})
    snaps[action["instance"]] = snap_id
    store.update_op(ctx["operation_id"], {"snapshots": snaps})
    return {"status": "DONE", "snapshot_id": snap_id}


def ecs_start(ctx, action):
    svc = _ecs_service(ctx)
    if svc is None:
        raise DriverError("ECS service not found")
    status = "NOOP"
    if svc["desiredCount"] == 0:
        aws("ecs").update_service(cluster=svc["clusterArn"], service=svc["serviceName"], desiredCount=1)
        status = "DONE"
    _poll(lambda: (_ecs_service(ctx) or {}).get("runningCount", 0), lambda n: n >= 1, "ECS task running")
    return {"status": status, "observed_state": RUNNING}


def ecs_stop(ctx, action):
    svc = _ecs_service(ctx)
    if svc is None:
        return {"status": "NOOP", "observed_state": ABSENT}
    status = "NOOP"
    if svc["desiredCount"] != 0:
        aws("ecs").update_service(cluster=svc["clusterArn"], service=svc["serviceName"], desiredCount=0)
        status = "DONE"
    _poll(lambda: (_ecs_service(ctx) or {}).get("runningCount", 0), lambda n: n == 0, "ECS tasks stopped")
    return {"status": status, "observed_state": STOPPED}


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
    """DNS points to the application only after the health gate (invariant A3). The wildcard record
    always points to the sleeping page, so going to sleep only removes the specific record. Without
    a hosted zone only the state is recorded, and the sleeping page redirects to the ALB address
    while the environment is awake."""
    from .store import get_store

    value = action["value"]
    zone = os.environ.get("HOSTED_ZONE_ID")
    domain = os.environ.get("DOMAIN")
    lb = _lb(ctx) if value == "APP" else None
    if value == "APP" and lb is None:
        raise DriverError("no ALB to point DNS to")
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
    "ec2_bastion.start": partial(ec2_start, role="bastion"),
    "ec2_bastion.stop": partial(ec2_stop, role="bastion"),
    "ec2_bastion.status_ok": partial(ec2_status_ok, role="bastion"),
    "ec2_workbench.start": partial(ec2_start, role="workbench"),
    "ec2_workbench.stop": partial(ec2_stop, role="workbench"),
    "ec2_workbench.status_ok": partial(ec2_status_ok, role="workbench"),
    "ebs_volume.snapshot": ebs_snapshot,
    "ecs_service.start": ecs_start,
    "ecs_service.stop": ecs_stop,
    "rds_instance.start": rds_start,
    "rds_instance.stop": rds_stop,
    "rds_instance.snapshot": rds_snapshot,
    "rds_instance.available": rds_available,
    "elbv2.target_healthy": elbv2_target_healthy,
    "dns.point": dns_point,
    "wait.seconds": wait_seconds,
}


def handler(event, context=None):
    """Lambda driver runner. Input: {"action": {...}, "ctx": {...}}. Errors raise so that Step Functions can catch them."""
    action, ctx = event["action"], event["ctx"]
    fn = ACTIONS.get(action["driver"])
    if fn is None:
        raise DriverError(f"driver not in the registry: {action['driver']}")
    res = fn(ctx, action)
    res["driver"] = action["driver"]
    res["instance"] = action.get("instance")
    return res
