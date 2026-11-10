"""Desired State function D(e, t).

D is pure: it depends only on the Lease, the Environment and `now`, with no hidden schedule or
timer. Changing the operating mode in the middle of a Lease is therefore safe; the next
evaluation starts from scratch.

Returns (desired, source), where desired is one of
  "AWAKE" | "ASLEEP:<level>" | "RECLAIMED" | "UNREGISTERED" | None (BLOCKED: not evaluated).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

DEFAULT_POLICY = {
    "mode": "schedule",
    "utc_offset_minutes": 420,  # Asia/Ho_Chi_Minh
    "schedule": {"days": [1, 2, 3, 4, 5], "start": "08:00", "end": "19:00"},
    "idle_timeout_minutes": None,
    "min_awake_minutes": 60,
    "off_hours_level": "deep",
    "idle_level": "deep",
    "manual_wake_hours": 2,
}


def parse_ts(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def in_schedule(policy: dict, now: datetime) -> bool:
    sch = policy.get("schedule")
    if not sch:
        return False
    local = now + timedelta(minutes=int(policy.get("utc_offset_minutes", 0)))
    if local.isoweekday() not in sch.get("days", []):
        return False
    hm = local.strftime("%H:%M")
    return sch["start"] <= hm < sch["end"]


def _idle(policy: dict, env: dict, now: datetime) -> bool:
    t = policy.get("idle_timeout_minutes")
    if not t:
        return False
    last = parse_ts(env.get("last_activity_at")) or parse_ts(env.get("awake_since"))
    if last is None:
        return False
    if now - last <= timedelta(minutes=int(t)):
        return False
    # Break-even rule: NAT and ALB bill by the started hour, so do not sleep before min_awake has elapsed.
    since = parse_ts(env.get("awake_since"))
    if since and now - since < timedelta(minutes=int(policy.get("min_awake_minutes", 60))):
        return False
    return True


def desired_state(lease: dict, env: dict, now: datetime) -> tuple:
    policy = {**DEFAULT_POLICY, **(lease.get("activity_policy") or {})}
    starts = parse_ts(lease.get("starts_at"))
    expires = parse_ts(lease.get("expires_at"))
    awake_now = env.get("actual") == "AWAKE"

    # 1. BLOCKED
    if env.get("blocked"):
        return None, None
    # 2. expired or reclaimed early
    if (expires and now >= expires) or lease.get("reclaim_requested"):
        return "RECLAIMED", ("EXPIRY" if expires and now >= expires else "MANUAL")
    # 3. unregister
    if env.get("unregister_requested"):
        return "UNREGISTERED", "MANUAL"
    # 4. an unexpired manual override
    ov = active_override(policy, env, now)
    if ov:
        return ov["value"], ov.get("source", "MANUAL")
    # 5. before the start date
    off = f"ASLEEP:{policy['off_hours_level']}"
    idle = f"ASLEEP:{policy['idle_level']}"
    if starts and now < starts:
        return off, "POLICY"

    mode = policy["mode"]
    if mode == "schedule":
        if in_schedule(policy, now):
            # 6. hybrid: inside the window but idle beyond the threshold (and past the break-even rule)
            if awake_now and _idle(policy, env, now):
                return idle, "IDLE"
            # Inside the window and asleep because idle: stay asleep until activity or a wake request
            if not awake_now and env.get("idle_slept_at") and policy.get("idle_timeout_minutes"):
                slept = parse_ts(env["idle_slept_at"])
                last = parse_ts(env.get("last_activity_at"))
                if slept and (last is None or last <= slept):
                    return idle, "IDLE"
            return "AWAKE", "POLICY"  # 7
        return off, "POLICY"  # 8

    if mode == "on_demand":
        if awake_now and _idle(policy, env, now):
            return idle, "IDLE"  # 9
        return ("AWAKE" if awake_now else idle), "POLICY"  # 10

    raise ValueError(f"unknown mode: {mode}")


def active_override(policy: dict, env: dict, now: datetime) -> dict | None:
    """The manual override in force at `now`, or None.

    In on_demand mode a Wake request only needs to hold until the environment is awake; after that
    the idle rule decides. The override is therefore consumed once the environment has become awake
    after the request, even if its expiry lies in the future. Without this, a wake request would keep
    the environment awake for manual_wake_hours regardless of idleness, and would wake it again after
    an idle sleep.
    """
    ov = env.get("override") or {}
    if not ov.get("value"):
        return None
    until = parse_ts(ov.get("until"))
    if until is not None and until <= now:
        return None
    if policy.get("mode") == "on_demand" and ov["value"] == "AWAKE":
        requested = parse_ts(ov.get("at"))
        if requested is None and until is not None:
            requested = until - timedelta(hours=int(policy.get("manual_wake_hours", 2)))
        awake_since = parse_ts(env.get("awake_since"))
        if awake_since is not None and requested is not None and awake_since >= requested:
            return None
    return ov


def manual_override(value: str, now: datetime, policy: dict | None, source: str = "MANUAL") -> dict:
    """Manual override with an expiry."""
    policy = {**DEFAULT_POLICY, **(policy or {})}
    if value == "AWAKE":
        hours = 2 if source == "PUBLIC_URL" else int(policy.get("manual_wake_hours", 2))
        return {"value": value, "at": iso(now), "until": iso(now + timedelta(hours=hours)), "source": source}
    # Manual sleep lasts until the next awake window (schedule) or the next wake request (on_demand)
    if policy["mode"] == "schedule":
        t = now
        for _ in range(8 * 24 * 4):
            t += timedelta(minutes=15)
            if in_schedule(policy, t) and not in_schedule(policy, t - timedelta(minutes=15)):
                return {"value": value, "at": iso(now), "until": iso(t), "source": source}
    return {"value": value, "at": iso(now), "until": None, "source": source}


# ---------------------------------------------------------------------------
# Next scheduled change, for display
# ---------------------------------------------------------------------------

def _windows(policy: dict, now: datetime, days: int = 8) -> list:
    """Awake windows [start, end) in UTC that end after `now`, for the next `days` days."""
    sch = policy.get("schedule") or {}
    offset = timedelta(minutes=int(policy.get("utc_offset_minutes", 0)))
    local_midnight = (now + offset).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for d in range(-1, days):
        day = local_midnight + timedelta(days=d)
        if day.isoweekday() not in sch.get("days", []):
            continue
        sh, sm = map(int, sch["start"].split(":"))
        eh, em = map(int, sch["end"].split(":"))
        s = day.replace(hour=sh, minute=sm) - offset
        e = day.replace(hour=eh, minute=em) - offset
        if e > now:
            out.append((s, e))
    return out


EXPIRY_HORIZON = timedelta(days=7)


def next_change(lease: dict, env: dict, now: datetime) -> dict | None:
    """Earliest time at which D(e, t) is expected to change, assuming no further activity or requests.

    Returns {"at", "to", "reason"} with reason one of manual, idle, schedule, expiry; or
    {"at": None, "to": "AWAKE", "reason": "request"} for an on_demand environment that is asleep;
    or None while an operation runs or when nothing is expected. Expiry is reported only when it is
    the next change and lies within EXPIRY_HORIZON.
    """
    if env.get("blocked") or env.get("status") in ("RECLAIMED", "VERIFYING") or env.get("active_operation_id"):
        return None
    policy = {**DEFAULT_POLICY, **(lease.get("activity_policy") or {})}
    current, _ = desired_state(lease, env, now)
    if current in (None, "RECLAIMED"):
        return None
    candidates = []
    expires = parse_ts(lease.get("expires_at"))
    if expires and now < expires <= now + EXPIRY_HORIZON:
        candidates.append((expires, "RECLAIMED", "expiry"))
    ov = active_override(policy, env, now)
    if ov:
        until = parse_ts(ov.get("until"))
        # An on_demand wake request is consumed when the environment becomes awake, not at `until`.
        on_demand_wake = policy.get("mode") == "on_demand" and ov["value"] == "AWAKE"
        if until and not on_demand_wake:
            after, _ = desired_state(lease, {**env, "override": None}, until)
            if after != current:
                candidates.append((until, after, "manual"))
    elif current == "AWAKE" and env.get("actual") == "AWAKE":
        if policy.get("idle_timeout_minutes"):
            last = parse_ts(env.get("last_activity_at")) or parse_ts(env.get("awake_since")) or now
            at = last + timedelta(minutes=int(policy["idle_timeout_minutes"]))
            since = parse_ts(env.get("awake_since"))
            if since:
                at = max(at, since + timedelta(minutes=int(policy.get("min_awake_minutes", 60))))
            candidates.append((max(at, now), f"ASLEEP:{policy['idle_level']}", "idle"))
        if policy["mode"] == "schedule":
            for s, e in _windows(policy, now):
                if s <= now < e:
                    candidates.append((e, f"ASLEEP:{policy['off_hours_level']}", "schedule"))
                    break
    elif current.startswith("ASLEEP") and policy["mode"] == "schedule" and not env.get("idle_slept_at"):
        for s, e in _windows(policy, now):
            if s > now:
                candidates.append((s, "AWAKE", "schedule"))
                break
    if not candidates:
        if policy["mode"] == "on_demand" and current.startswith("ASLEEP") and not ov:
            return {"at": None, "to": "AWAKE", "reason": "request"}
        return None
    at, to, reason = min(candidates, key=lambda c: c[0])
    return {"at": iso(at), "to": to, "reason": reason}
