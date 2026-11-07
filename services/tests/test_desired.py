import unittest
from datetime import datetime, timedelta, timezone

from infraflow.desired import desired_state, manual_override

UTC = timezone.utc


def t(s):  # Asia/Ho_Chi_Minh local time -> UTC
    return datetime.fromisoformat(s).replace(tzinfo=timezone(timedelta(hours=7))).astimezone(UTC)


LEASE = {"starts_at": "2026-11-01T00:00:00Z", "expires_at": "2027-01-01T00:00:00Z",
         "activity_policy": {"mode": "schedule", "utc_offset_minutes": 420,
                             "schedule": {"days": [1, 2, 3, 4, 5], "start": "08:00", "end": "19:00"}}}


class TestDesired(unittest.TestCase):
    def test_schedule(self):
        self.assertEqual(desired_state(LEASE, {}, t("2026-11-02T09:00")), ("AWAKE", "POLICY"))  # Monday
        self.assertEqual(desired_state(LEASE, {}, t("2026-11-02T20:00"))[0], "ASLEEP:deep")
        self.assertEqual(desired_state(LEASE, {}, t("2026-11-07T10:00"))[0], "ASLEEP:deep")  # Saturday

    def test_priority(self):
        env = {"override": {"value": "AWAKE", "until": "2099-01-01T00:00:00Z"}}
        self.assertEqual(desired_state(LEASE, env, t("2026-11-07T10:00"))[0], "AWAKE")  # manual beats schedule
        self.assertEqual(desired_state(LEASE, env, t("2027-01-02T10:00"))[0], "RECLAIMED")  # expiry beats manual
        self.assertEqual(desired_state(LEASE, dict(env, blocked=True), t("2026-11-07T10:00")), (None, None))
        self.assertEqual(desired_state(LEASE, {}, t("2026-10-30T10:00"))[0], "ASLEEP:deep")  # before start

    def test_override_expires(self):
        env = {"override": {"value": "AWAKE", "until": "2026-11-07T00:00:00Z"}}
        self.assertEqual(desired_state(LEASE, env, t("2026-11-07T10:00"))[0], "ASLEEP:deep")

    def test_on_demand_idle_with_break_even(self):
        lease = dict(LEASE, activity_policy={"mode": "on_demand", "idle_timeout_minutes": 30})
        now = t("2026-11-02T10:00")
        env = {"actual": "AWAKE", "awake_since": (now - timedelta(minutes=40)).isoformat(),
               "last_activity_at": (now - timedelta(minutes=35)).isoformat()}
        # idle 35 > 30 minutes, but awake only 40 < 60 minutes: the break-even rule keeps it awake
        self.assertEqual(desired_state(lease, env, now)[0], "AWAKE")
        env["awake_since"] = (now - timedelta(minutes=70)).isoformat()
        self.assertEqual(desired_state(lease, env, now), ("ASLEEP:deep", "IDLE"))
        self.assertEqual(desired_state(lease, {"actual": "ASLEEP:deep"}, now)[0], "ASLEEP:deep")

    def test_mode_switch_is_stateless(self):
        now = t("2026-11-02T21:00")
        env = {"actual": "AWAKE", "awake_since": t("2026-11-02T08:00").isoformat(), "last_activity_at": now.isoformat()}
        self.assertEqual(desired_state(LEASE, env, now)[0], "ASLEEP:deep")
        on_demand = dict(LEASE, activity_policy={"mode": "on_demand", "idle_timeout_minutes": 30})
        self.assertEqual(desired_state(on_demand, env, now)[0], "AWAKE")

    def test_manual_sleep_until_next_window(self):
        ov = manual_override("ASLEEP:deep", t("2026-11-02T12:00"), LEASE["activity_policy"])
        self.assertEqual(ov["until"], "2026-11-03T01:00:00Z")  # 08:00 Tuesday local time
        ov = manual_override("AWAKE", t("2026-11-02T12:00"), LEASE["activity_policy"], source="PUBLIC_URL")
        self.assertEqual(ov["until"], "2026-11-02T07:00:00Z")


if __name__ == "__main__":
    unittest.main()
