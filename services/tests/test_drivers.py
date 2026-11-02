import unittest

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

    def test_unknown_driver_rejected(self):
        with self.assertRaises(drivers.DriverError):
            drivers.handler({"action": {"driver": "shell.exec"}, "ctx": CTX})


if __name__ == "__main__":
    unittest.main()
