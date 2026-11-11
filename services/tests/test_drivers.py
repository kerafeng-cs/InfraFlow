import unittest
import unittest.mock

from infraflow import drivers


class Exc(Exception):
    pass


class FakeEC2:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def describe_instances(self, Filters):
        if self.state is None:
            return {"Reservations": []}
        return {"Reservations": [{"Instances": [{"InstanceId": "i-1", "State": {"Name": self.state}}]}]}

    def start_instances(self, InstanceIds):
        self.calls.append("start")
        self.state = "running"

    def stop_instances(self, InstanceIds):
        self.calls.append("stop")
        self.state = "stopped"


class FakeRDS:
    class exceptions:
        DBInstanceNotFoundFault = Exc
        DBSnapshotNotFoundFault = Exc

    def __init__(self, status):
        self.status = status
        self.calls = []
        self.seq = []

    def describe_db_instances(self, DBInstanceIdentifier):
        if self.status is None:
            raise Exc()
        if self.seq:
            self.status = self.seq.pop(0)
        return {"DBInstances": [{"DBInstanceIdentifier": DBInstanceIdentifier, "DBInstanceStatus": self.status}]}

    def stop_db_instance(self, DBInstanceIdentifier):
        self.calls.append("stop")
        self.seq = ["stopping", "stopping", "stopped"]

    def start_db_instance(self, DBInstanceIdentifier):
        self.calls.append("start")
        self.seq = ["starting", "available"]


class FakeElastiCache:
    class exceptions:
        CacheClusterNotFoundFault = Exc

    def __init__(self, status):
        self.status = status

    def describe_cache_clusters(self, CacheClusterId):
        if self.status is None:
            raise Exc()
        return {"CacheClusters": [{"CacheClusterId": CacheClusterId, "CacheClusterStatus": self.status}]}


class FakeEC2Volumes:
    def __init__(self, volume=True):
        self.volume = volume
        self.snapshots = []
        self.filters = []

    def describe_volumes(self, Filters):
        self.filters.append(Filters)
        return {"Volumes": [{"VolumeId": "vol-1"}] if self.volume else []}

    def describe_snapshots(self, OwnerIds=None, Filters=None, SnapshotIds=None):
        if SnapshotIds:
            return {"Snapshots": [{"SnapshotId": SnapshotIds[0], "State": "completed"}]}
        return {"Snapshots": list(self.snapshots)}

    def create_snapshot(self, VolumeId, Description, TagSpecifications):
        snap = {"SnapshotId": f"snap-{len(self.snapshots) + 1}", "State": "pending"}
        self.snapshots.append(snap)
        return snap


class FakeECS:
    class exceptions:
        ClusterNotFoundException = Exc

    def __init__(self, desired):
        self.desired = desired
        self.updates = []

    def describe_services(self, cluster, services):
        if self.desired is None:
            raise Exc()
        return {"services": [{"serviceName": services[0], "clusterArn": cluster, "status": "ACTIVE",
                              "desiredCount": self.desired, "runningCount": self.desired}]}

    def update_service(self, cluster, service, desiredCount):
        self.updates.append(desiredCount)
        self.desired = desiredCount


class FakeSQS:
    class exceptions:
        QueueDoesNotExist = Exc

    def __init__(self, exists):
        self.exists = exists

    def get_queue_url(self, QueueName):
        if not self.exists:
            raise Exc()
        return {"QueueUrl": f"https://sqs/{QueueName}"}


class FakeOpenSearch:
    class exceptions:
        ResourceNotFoundException = Exc

    def __init__(self, status):
        self.status = status
        self.names = []

    def describe_domain(self, DomainName):
        self.names.append(DomainName)
        if self.status is None:
            raise Exc()
        return {"DomainStatus": {"DomainName": DomainName, "Deleted": self.status == "deleted"}}


class FakeStore:
    def __init__(self):
        self.ops = {"op": {}}

    def get_op(self, op_id):
        return self.ops.get(op_id)

    def update_op(self, op_id, fields):
        self.ops.setdefault(op_id, {}).update(fields)


CTX = {"environment_id": "e", "name_prefix": "e", "operation_id": "op"}


class TestDrivers(unittest.TestCase):
    def setUp(self):
        drivers.SLEEP = lambda s: None

    def test_ec2_idempotent(self):
        ec2 = FakeEC2("running")
        drivers.set_clients({"ec2": ec2})
        self.assertEqual(drivers.handler({"action": {"driver": "ec2_instance.stop", "instance": "app"}, "ctx": CTX})["status"], "DONE")
        self.assertEqual(drivers.handler({"action": {"driver": "ec2_instance.stop", "instance": "app"}, "ctx": CTX})["status"], "NOOP")
        self.assertEqual(ec2.calls, ["stop"])
        self.assertEqual(drivers.ec2_describe(CTX), "STOPPED")

    def test_rds_stop_waits_until_stopped(self):
        rds = FakeRDS("available")
        drivers.set_clients({"rds": rds})
        r = drivers.handler({"action": {"driver": "rds_instance.stop", "instance": "database"}, "ctx": CTX})
        self.assertEqual((r["status"], rds.status), ("DONE", "stopped"))
        r = drivers.handler({"action": {"driver": "rds_instance.stop", "instance": "database"}, "ctx": CTX})
        self.assertEqual(r["status"], "NOOP")
        self.assertEqual(rds.calls, ["stop"])

    def test_rds_absent_vs_snapshotted(self):
        drivers.set_clients({"rds": FakeRDS(None)})
        self.assertEqual(drivers.rds_describe(CTX), "ABSENT")
        self.assertEqual(drivers.rds_describe(dict(CTX, snapshots={"database": "snap-1"})), "SNAPSHOTTED")

    def test_elasticache_states(self):
        for status, want in ((None, "ABSENT"), ("creating", "PRESENT"), ("available", "PRESENT"), ("deleting", "ABSENT")):
            drivers.set_clients({"elasticache": FakeElastiCache(status)})
            self.assertEqual(drivers.elasticache_describe(CTX), want, status)

    def test_ec2_drivers_find_the_instance_by_role(self):
        names = []

        class Recorder(FakeEC2):
            def describe_instances(self, Filters):
                names.append(next(f["Values"][0] for f in Filters if f["Name"] == "tag:Name"))
                return super().describe_instances(Filters)

        drivers.set_clients({"ec2": Recorder("running")})
        drivers.handler({"action": {"driver": "ec2_bastion.stop", "instance": "bastion"}, "ctx": CTX})
        drivers.OBSERVE["ec2_workbench.describe"](CTX)
        drivers.OBSERVE["ec2_instance.describe"](CTX)
        self.assertEqual(sorted(set(names)), ["e-app", "e-bastion", "e-workbench"])

    def test_ebs_volume_snapshot_is_recorded_and_idempotent(self):
        from unittest import mock
        ec2, store = FakeEC2Volumes(), FakeStore()
        drivers.set_clients({"ec2": ec2})
        with mock.patch("infraflow.store.get_store", return_value=store):
            r1 = drivers.handler({"action": {"driver": "ebs_volume.snapshot", "instance": "volume"}, "ctx": CTX})
            r2 = drivers.handler({"action": {"driver": "ebs_volume.snapshot", "instance": "volume"}, "ctx": CTX})
        self.assertEqual((r1["snapshot_id"], r2["snapshot_id"], len(ec2.snapshots)), ("snap-1", "snap-1", 1))
        self.assertEqual(store.ops["op"]["snapshots"], {"volume": "snap-1"})
        self.assertEqual(drivers.ebs_describe(dict(CTX, instance="volume")), "RUNNING")
        ec2.volume = False
        self.assertEqual(drivers.ebs_describe(dict(CTX, instance="volume")), "ABSENT")
        self.assertEqual(drivers.ebs_describe(dict(CTX, instance="volume", snapshots={"volume": "snap-1"})), "SNAPSHOTTED")

    def test_observe_passes_the_instance_name(self):
        from infraflow.ics.model import build_graph
        from tests.test_ics import CAT
        drivers.set_clients({"ec2": FakeEC2Volumes(volume=False)})
        g = build_graph(CAT, "ml-workbench@1.0.0")
        with unittest.mock.patch.dict(drivers.OBSERVE, {"vpc.describe": lambda c: "PRESENT",
                                                       "nat_gateway.describe": lambda c: "ABSENT",
                                                       "ec2_workbench.describe": lambda c: "ABSENT"}):
            got = drivers.observe_all(g, dict(CTX, snapshots={"volume": "snap-9"}))
        self.assertEqual(got["volume"], "SNAPSHOTTED")

    def test_ecs_service_states_and_actions(self):
        ecs = FakeECS(1)
        drivers.set_clients({"ecs": ecs})
        self.assertEqual(drivers.ecs_describe(CTX), "RUNNING")
        self.assertEqual(drivers.handler({"action": {"driver": "ecs_service.stop", "instance": "service"}, "ctx": CTX})["status"], "DONE")
        self.assertEqual(drivers.ecs_describe(CTX), "STOPPED")
        self.assertEqual(drivers.handler({"action": {"driver": "ecs_service.stop", "instance": "service"}, "ctx": CTX})["status"], "NOOP")
        self.assertEqual(drivers.handler({"action": {"driver": "ecs_service.start", "instance": "service"}, "ctx": CTX})["status"], "DONE")
        self.assertEqual(ecs.updates, [0, 1])
        drivers.set_clients({"ecs": FakeECS(None)})
        self.assertEqual(drivers.ecs_describe(CTX), "ABSENT")

    def test_sqs_and_opensearch_presence(self):
        drivers.set_clients({"sqs": FakeSQS(True)})
        self.assertEqual(drivers.sqs_describe(CTX), "PRESENT")
        drivers.set_clients({"sqs": FakeSQS(False)})
        self.assertEqual(drivers.sqs_describe(CTX), "ABSENT")
        for status, want in ((None, "ABSENT"), ("active", "PRESENT"), ("deleted", "ABSENT")):
            os_client = FakeOpenSearch(status)
            drivers.set_clients({"opensearch": os_client})
            self.assertEqual(drivers.opensearch_describe(dict(CTX, name_prefix="a-very-long-lease-name-dev")), want)
            self.assertLessEqual(len(os_client.names[0]), 28)

    def test_every_registered_driver_is_implemented(self):
        import yaml
        from pathlib import Path
        reg = yaml.safe_load((Path(__file__).resolve().parents[2] / "ics" / "registry.yaml").read_text())
        implemented = set(drivers.OBSERVE) | set(drivers.ACTIONS) | {"terraform.presence", "terraform.restore"}
        self.assertEqual(sorted(set(reg["drivers"]) - implemented), [])

    def test_unknown_driver_rejected(self):
        with self.assertRaises(drivers.DriverError):
            drivers.handler({"action": {"driver": "shell.exec"}, "ctx": CTX})


if __name__ == "__main__":
    unittest.main()
