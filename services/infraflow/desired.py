"""Hàm Desired State D(e, t) (TD mục 10.2, IC mục 9.2).

Là hàm thuần: chỉ phụ thuộc Lease, Environment và thời điểm `now`, không có lịch hay bộ hẹn giờ ẩn.
Vì vậy đổi chế độ hoạt động giữa kỳ thuê là an toàn: lượt sau tính lại từ đầu.

Giá trị trả về: (desired, source) với desired thuộc
  "AWAKE" | "ASLEEP:<level>" | "RECLAIMED" | "UNREGISTERED" | None (BLOCKED: không tính).
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
    # Luật hòa vốn: NAT, ALB tính tròn giờ; chưa thức đủ min_awake thì chưa cho ngủ.
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
    # 2. hết hạn hoặc thu hồi sớm
    if (expires and now >= expires) or lease.get("reclaim_requested"):
        return "RECLAIMED", ("EXPIRY" if expires and now >= expires else "MANUAL")
    # 3. unregister
    if env.get("unregister_requested"):
        return "UNREGISTERED", "MANUAL"
    # 4. thao tác tay còn hiệu lực
    ov = env.get("override") or {}
    until = parse_ts(ov.get("until"))
    if ov.get("value") and (until is None or until > now):
        return ov["value"], ov.get("source", "MANUAL")
    # 5. chưa tới ngày bắt đầu
    off = f"ASLEEP:{policy['off_hours_level']}"
    idle = f"ASLEEP:{policy['idle_level']}"
    if starts and now < starts:
        return off, "POLICY"

    mode = policy["mode"]
    if mode == "schedule":
        if in_schedule(policy, now):
            # 6. lai: trong khung nhưng rảnh quá ngưỡng (và đã qua luật hòa vốn)
            if awake_now and _idle(policy, env, now):
                return idle, "IDLE"
            # Trong khung, đã ngủ vì rảnh: không tự thức lại cho tới khi có hoạt động/yêu cầu
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

    raise ValueError(f"chế độ lạ: {mode}")


def manual_override(value: str, now: datetime, policy: dict | None, source: str = "MANUAL") -> dict:
    """Thao tác tay có thời hạn (TD mục 9.4)."""
    policy = {**DEFAULT_POLICY, **(policy or {})}
    if value == "AWAKE":
        hours = 2 if source == "PUBLIC_URL" else int(policy.get("manual_wake_hours", 2))
        return {"value": value, "until": iso(now + timedelta(hours=hours)), "source": source}
    # Ngủ tay: hiệu lực tới đầu khung thức kế tiếp (schedule) hoặc tới yêu cầu thức kế tiếp (on_demand)
    if policy["mode"] == "schedule":
        t = now
        for _ in range(8 * 24 * 4):
            t += timedelta(minutes=15)
            if in_schedule(policy, t) and not in_schedule(policy, t - timedelta(minutes=15)):
                return {"value": value, "until": iso(t), "source": source}
    return {"value": value, "until": None, "source": source}
