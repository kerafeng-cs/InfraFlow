"""Control data storage.

DynamoStore uses DynamoDB; MemoryStore serves unit tests. Both expose the same interface.
Environment lock: `active_operation_id` is set with a conditional write.
"""

from __future__ import annotations

import copy
import json
import os
from decimal import Decimal


class LockError(Exception):
    pass


class VersionConflict(Exception):
    pass


def _to_ddb(obj):
    return json.loads(json.dumps(obj), parse_float=Decimal)


def _from_ddb(obj):
    if isinstance(obj, list):
        return [_from_ddb(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _from_ddb(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    return obj


class MemoryStore:
    def __init__(self):
        self.t = {"leases": {}, "environments": {}, "operations": {}, "state_log": [], "idempotency": {}, "orphans": {}}

    # ---- lease ----
    def put_lease(self, item):
        self.t["leases"][item["lease_id"]] = copy.deepcopy(item)

    def get_lease(self, lease_id):
        return copy.deepcopy(self.t["leases"].get(lease_id))

    def list_leases(self, org_id):
        return [copy.deepcopy(x) for x in self.t["leases"].values() if x["org_id"] == org_id]

    def update_lease(self, lease_id, fields, expected_version=None):
        cur = self.t["leases"][lease_id]
        if expected_version is not None and cur.get("version") != expected_version:
            raise VersionConflict(lease_id)
        cur.update(copy.deepcopy(fields))
        cur["version"] = cur.get("version", 0) + 1
        return copy.deepcopy(cur)

    # ---- environment ----
    def put_env(self, item):
        self.t["environments"][item["environment_id"]] = copy.deepcopy(item)

    def get_env(self, env_id):
        return copy.deepcopy(self.t["environments"].get(env_id))

    def list_envs(self, lease_id=None):
        return [copy.deepcopy(x) for x in self.t["environments"].values() if lease_id is None or x["lease_id"] == lease_id]

    def find_env_by_host(self, host):
        return next((copy.deepcopy(x) for x in self.t["environments"].values() if x.get("host") == host), None)

    def update_env(self, env_id, fields, remove=()):
        cur = self.t["environments"][env_id]
        cur.update(copy.deepcopy(fields))
        for k in remove:
            cur.pop(k, None)
        return copy.deepcopy(cur)

    def acquire_lock(self, env_id, operation_id):
        cur = self.t["environments"][env_id]
        if cur.get("active_operation_id") or cur.get("blocked"):
            raise LockError(env_id)
        cur["active_operation_id"] = operation_id

    def release_lock(self, env_id, operation_id):
        cur = self.t["environments"][env_id]
        if cur.get("active_operation_id") == operation_id:
            cur.pop("active_operation_id", None)

    # ---- operation ----
    def put_op(self, item):
        self.t["operations"][item["operation_id"]] = copy.deepcopy(item)

    def get_op(self, op_id):
        return copy.deepcopy(self.t["operations"].get(op_id))

    def update_op(self, op_id, fields):
        self.t["operations"][op_id].update(copy.deepcopy(fields))

    def list_ops(self, env_id, limit=20):
        ops = [x for x in self.t["operations"].values() if x.get("environment_id") == env_id]
        return copy.deepcopy(sorted(ops, key=lambda o: o["requested_at"], reverse=True)[:limit])

    # ---- state log ----
    def append_state_log(self, env_id, at, instance, frm, to, operation_id):
        self.t["state_log"].append({"environment_id": env_id, "at": at, "instance": instance,
                                    "from": frm, "to": to, "operation_id": operation_id})

    def list_state_log(self, env_id):
        return copy.deepcopy(sorted((x for x in self.t["state_log"] if x["environment_id"] == env_id), key=lambda x: x["at"]))

    # ---- idempotency ----
    def get_idem(self, key):
        return copy.deepcopy(self.t["idempotency"].get(key))

    def put_idem(self, key, item):
        if key in self.t["idempotency"]:
            raise LockError(key)
        self.t["idempotency"][key] = copy.deepcopy(item)

    # ---- orphans ----
    def put_orphan(self, item):
        self.t["orphans"][item["resource_arn"]] = copy.deepcopy(item)

    def list_orphans(self):
        return copy.deepcopy(list(self.t["orphans"].values()))


class DynamoStore:
    def __init__(self, prefix: str | None = None, resource=None):
        import boto3
        from boto3.dynamodb.conditions import Attr, Key  # noqa: F401

        self._Key, self._Attr = Key, Attr
        prefix = prefix or os.environ.get("TABLE_PREFIX", "infraflow")
        ddb = resource or boto3.resource("dynamodb")
        self.leases = ddb.Table(f"{prefix}-leases")
        self.envs = ddb.Table(f"{prefix}-environments")
        self.ops = ddb.Table(f"{prefix}-operations")
        self.log = ddb.Table(f"{prefix}-state-log")
        self.idem = ddb.Table(f"{prefix}-idempotency")
        self.orphans = ddb.Table(f"{prefix}-orphans")

    @staticmethod
    def _items(table, **kw):
        out, start = [], None
        while True:
            if start:
                kw["ExclusiveStartKey"] = start
            r = table.query(**kw) if "KeyConditionExpression" in kw else table.scan(**kw)
            out += r.get("Items", [])
            start = r.get("LastEvaluatedKey")
            if not start:
                return [_from_ddb(x) for x in out]

    @staticmethod
    def _update_expr(fields, remove=()):
        names, values, sets = {}, {}, []
        for i, (k, v) in enumerate(fields.items()):
            names[f"#f{i}"] = k
            values[f":v{i}"] = _to_ddb(v)
            sets.append(f"#f{i} = :v{i}")
        expr = ("SET " + ", ".join(sets)) if sets else ""
        if remove:
            for j, k in enumerate(remove):
                names[f"#r{j}"] = k
            expr += (" " if expr else "") + "REMOVE " + ", ".join(f"#r{j}" for j in range(len(remove)))
        return expr, names, values

    # ---- lease ----
    def put_lease(self, item):
        self.leases.put_item(Item=_to_ddb(item))

    def get_lease(self, lease_id):
        r = self.leases.get_item(Key={"lease_id": lease_id})
        return _from_ddb(r["Item"]) if "Item" in r else None

    def list_leases(self, org_id):
        return self._items(self.leases, IndexName="org_id", KeyConditionExpression=self._Key("org_id").eq(org_id))

    def update_lease(self, lease_id, fields, expected_version=None):
        from botocore.exceptions import ClientError

        fields = dict(fields)
        expr, names, values = self._update_expr(fields)
        expr += ", #ver = if_not_exists(#ver, :zero) + :one"
        names["#ver"] = "version"
        values.update({":zero": 0, ":one": 1})
        kw = dict(Key={"lease_id": lease_id}, UpdateExpression=expr, ExpressionAttributeNames=names,
                  ExpressionAttributeValues=values, ReturnValues="ALL_NEW")
        if expected_version is not None:
            kw["ConditionExpression"] = "#ver = :exp"
            values[":exp"] = expected_version
        try:
            return _from_ddb(self.leases.update_item(**kw)["Attributes"])
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise VersionConflict(lease_id) from e
            raise

    # ---- environment ----
    def put_env(self, item):
        self.envs.put_item(Item=_to_ddb(item))

    def get_env(self, env_id):
        r = self.envs.get_item(Key={"environment_id": env_id})
        return _from_ddb(r["Item"]) if "Item" in r else None

    def list_envs(self, lease_id=None):
        if lease_id is None:
            return self._items(self.envs)
        return self._items(self.envs, IndexName="lease_id", KeyConditionExpression=self._Key("lease_id").eq(lease_id))

    def find_env_by_host(self, host):
        items = self._items(self.envs, IndexName="host", KeyConditionExpression=self._Key("host").eq(host))
        return items[0] if items else None

    def update_env(self, env_id, fields, remove=()):
        expr, names, values = self._update_expr(fields, remove)
        kw = dict(Key={"environment_id": env_id}, UpdateExpression=expr, ExpressionAttributeNames=names,
                  ReturnValues="ALL_NEW")
        if values:
            kw["ExpressionAttributeValues"] = values
        return _from_ddb(self.envs.update_item(**kw)["Attributes"])

    def acquire_lock(self, env_id, operation_id):
        from botocore.exceptions import ClientError

        try:
            self.envs.update_item(
                Key={"environment_id": env_id},
                UpdateExpression="SET active_operation_id = :op",
                ConditionExpression="attribute_not_exists(active_operation_id) AND (attribute_not_exists(blocked) OR blocked = :f)",
                ExpressionAttributeValues={":op": operation_id, ":f": False})
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise LockError(env_id) from e
            raise

    def release_lock(self, env_id, operation_id):
        from botocore.exceptions import ClientError

        try:
            self.envs.update_item(Key={"environment_id": env_id}, UpdateExpression="REMOVE active_operation_id",
                                  ConditionExpression="active_operation_id = :op",
                                  ExpressionAttributeValues={":op": operation_id})
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

    # ---- operation ----
    def put_op(self, item):
        self.ops.put_item(Item=_to_ddb(item))

    def get_op(self, op_id):
        r = self.ops.get_item(Key={"operation_id": op_id})
        return _from_ddb(r["Item"]) if "Item" in r else None

    def update_op(self, op_id, fields):
        expr, names, values = self._update_expr(fields)
        self.ops.update_item(Key={"operation_id": op_id}, UpdateExpression=expr,
                             ExpressionAttributeNames=names, ExpressionAttributeValues=values)

    def list_ops(self, env_id, limit=20):
        r = self.ops.query(IndexName="environment_id", KeyConditionExpression=self._Key("environment_id").eq(env_id),
                           ScanIndexForward=False, Limit=limit)
        return [_from_ddb(x) for x in r.get("Items", [])]

    # ---- state log ----
    def append_state_log(self, env_id, at, instance, frm, to, operation_id):
        self.log.put_item(Item={"environment_id": env_id, "at_instance": f"{at}#{instance}", "at": at,
                                "instance": instance, "from": frm, "to": to, "operation_id": operation_id})

    def list_state_log(self, env_id):
        return self._items(self.log, KeyConditionExpression=self._Key("environment_id").eq(env_id))

    # ---- idempotency ----
    def get_idem(self, key):
        r = self.idem.get_item(Key={"scope_key": key})
        return _from_ddb(r["Item"]) if "Item" in r else None

    def put_idem(self, key, item):
        from botocore.exceptions import ClientError

        try:
            self.idem.put_item(Item=_to_ddb({"scope_key": key, **item}), ConditionExpression="attribute_not_exists(scope_key)")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise LockError(key) from e
            raise

    # ---- orphans ----
    def put_orphan(self, item):
        self.orphans.put_item(Item=_to_ddb(item))

    def list_orphans(self):
        return self._items(self.orphans)


_STORE = None


def get_store():
    global _STORE
    if _STORE is None:
        _STORE = DynamoStore()
    return _STORE


def set_store(s):
    global _STORE
    _STORE = s
