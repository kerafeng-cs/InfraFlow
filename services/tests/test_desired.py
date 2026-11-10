import unittest
from datetime import datetime, timedelta, timezone

from infraflow.desired import desired_state, iso, manual_override, next_change

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


ON_DEMAND = dict(LEASE, activity_policy={"mode": "on_demand", "utc_offset_minutes": 420, "idle_timeout_minutes": 20})


class TestOnDemandWake(unittest.TestCase):
    def test_wake_request_holds_only_until_awake(self):
        asked = t("2026-11-02T10:00")
        ov = manual_override("AWAKE", asked, ON_DEMAND["activity_policy"])
        # Requested, not yet awake: the override drives the wake
        self.assertEqual(desired_state(ON_DEMAND, {"actual": "ASLEEP:deep", "override": ov}, asked)[0], "AWAKE")
        # Awake since 10:20; at 11:30 the last request was 70 minutes ago: idle rule applies despite the 2 h override
        env = {"actual": "AWAKE", "override": ov, "awake_since": iso(t("2026-11-02T10:20")),
               "last_activity_at": iso(t("2026-11-02T10:30"))}
        self.assertEqual(desired_state(ON_DEMAND, env, t("2026-11-02T11:30")), ("ASLEEP:deep", "IDLE"))
        # After the idle sleep the same override does not wake it again
        env["actual"] = "ASLEEP:deep"
        self.assertEqual(desired_state(ON_DEMAND, env, t("2026-11-02T11:40"))[0], "ASLEEP:deep")

    def test_schedule_mode_keeps_manual_wake_for_its_duration(self):
        asked = t("2026-11-07T10:00")  # Saturday, outside the window
        ov = manual_override("AWAKE", asked, LEASE["activity_policy"])
        env = {"actual": "AWAKE", "override": ov, "awake_since": iso(t("2026-11-07T10:20"))}
        self.assertEqual(desired_state(LEASE, env, t("2026-11-07T11:50"))[0], "AWAKE")
        self.assertEqual(desired_state(LEASE, env, t("2026-11-07T12:10"))[0], "ASLEEP:deep")


class TestNextChange(unittest.TestCase):
    def test_on_demand_awake_sleeps_at_later_of_idle_and_break_even(self):
        now = t("2026-11-02T10:30")
        env = {"actual": "AWAKE", "awake_since": iso(t("2026-11-02T10:00")), "last_activity_at": iso(t("2026-11-02T10:25"))}
        # idle deadline 10:45, break-even 11:00 -> 11:00
        self.assertEqual(next_change(ON_DEMAND, env, now),
                         {"at": iso(t("2026-11-02T11:00")), "to": "ASLEEP:deep", "reason": "idle"})

    def test_on_demand_asleep_wakes_on_request_and_expiry_shows_when_close(self):
        self.assertEqual(next_change(ON_DEMAND, {"actual": "ASLEEP:deep"}, t("2026-11-02T10:30")),
                         {"at": None, "to": "AWAKE", "reason": "request"})
        self.assertEqual(next_change(ON_DEMAND, {"actual": "ASLEEP:deep"}, t("2026-12-28T10:30")),
                         {"at": "2027-01-01T00:00:00Z", "to": "RECLAIMED", "reason": "expiry"})

    def test_nothing_while_an_operation_runs(self):
        self.assertIsNone(next_change(ON_DEMAND, {"actual": "ASLEEP:deep", "active_operation_id": "op"}, t("2026-11-02T10:30")))

    def test_schedule_wakes_at_next_window(self):
        friday_night = t("2026-11-06T20:00")
        self.assertEqual(next_change(LEASE, {"actual": "ASLEEP:deep"}, friday_night),
                         {"at": iso(t("2026-11-09T08:00")), "to": "AWAKE", "reason": "schedule"})

    def test_schedule_awake_sleeps_at_window_end(self):
        env = {"actual": "AWAKE", "awake_since": iso(t("2026-11-02T08:00"))}
        self.assertEqual(next_change(LEASE, env, t("2026-11-02T12:00")),
                         {"at": iso(t("2026-11-02T19:00")), "to": "ASLEEP:deep", "reason": "schedule"})

    def test_manual_override_end(self):
        ov = manual_override("AWAKE", t("2026-11-07T10:00"), LEASE["activity_policy"])
        env = {"actual": "AWAKE", "override": ov, "awake_since": iso(t("2026-11-07T10:20"))}
        self.assertEqual(next_change(LEASE, env, t("2026-11-07T11:00")),
                         {"at": iso(t("2026-11-07T12:00")), "to": "ASLEEP:deep", "reason": "manual"})

    def test_blocked_or_reclaimed_has_none(self):
        self.assertIsNone(next_change(LEASE, {"blocked": True}, t("2026-11-02T12:00")))
        self.assertIsNone(next_change(LEASE, {"status": "RECLAIMED"}, t("2026-11-02T12:00")))
