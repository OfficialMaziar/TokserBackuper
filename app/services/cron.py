"""Cron expression parsing and next-run calculation.

Implements the standard 5-field cron syntax (minute hour day-of-month month
day-of-week) with ``*``, ranges, lists, steps and month/day names. Also
provides timezone-aware scheduling helpers used by the built-in scheduler.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
DOW_NAMES = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}

FIELD_RANGES = {
    "minute": (0, 59),
    "hour": (0, 23),
    "dom": (1, 31),
    "month": (1, 12),
    "dow": (0, 6),  # 0 = Sunday (standard cron)
}


class CronError(ValueError):
    pass


def _parse_value(token: str, names: dict[str, int] | None) -> int:
    token = token.strip().lower()
    if names and token in names:
        return names[token]
    try:
        return int(token)
    except ValueError as exc:
        raise CronError(f"Invalid cron value: {token}") from exc


def _expand_field(field: str, lo: int, hi: int, names: dict[str, int] | None = None) -> set[int]:
    values: set[int] = set()
    if field == "*":
        return set(range(lo, hi + 1))
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise CronError("Empty cron field part")
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            try:
                step = int(step_s)
            except ValueError as exc:
                raise CronError(f"Invalid cron step: {step_s}") from exc
            if step <= 0:
                raise CronError("Cron step must be positive")
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start = _parse_value(a, names)
            end = _parse_value(b, names)
        else:
            start = end = _parse_value(part, names)
        if start < lo or end > hi or start > end:
            raise CronError(f"Cron value out of range: {part} ({lo}-{hi})")
        values.update(range(start, end + 1, step))
    if not values:
        raise CronError("Cron field produced no values")
    return values


class CronExpression:
    def __init__(self, expression: str):
        parts = (expression or "").split()
        if len(parts) != 5:
            raise CronError("Cron expression must have exactly 5 fields")
        self.expression = " ".join(parts)
        self.minutes = _expand_field(parts[0], *FIELD_RANGES["minute"])
        self.hours = _expand_field(parts[1], *FIELD_RANGES["hour"])
        self.days = _expand_field(parts[2], *FIELD_RANGES["dom"])
        self.months = _expand_field(parts[3], *FIELD_RANGES["month"], MONTH_NAMES)
        self.weekdays = _expand_field(parts[4], *FIELD_RANGES["dow"], DOW_NAMES)
        self._dom_restricted = parts[2] != "*"
        self._dow_restricted = parts[4] != "*"

    def _day_matches(self, dt: datetime) -> bool:
        dom_ok = dt.day in self.days
        # Python: Monday=0 .. Sunday=6 ; cron: Sunday=0 .. Saturday=6
        cron_dow = (dt.weekday() + 1) % 7
        dow_ok = cron_dow in self.weekdays
        if self._dom_restricted and self._dow_restricted:
            return dom_ok or dow_ok
        if self._dom_restricted:
            return dom_ok
        if self._dow_restricted:
            return dow_ok
        return True

    def next_after(self, after: datetime, tz: ZoneInfo | timezone | None = None, limit_days: int = 366 * 5) -> datetime | None:
        """Return the next matching time strictly after ``after`` (UTC)."""
        tz = tz or timezone.utc
        local = after.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
        deadline = local + timedelta(days=limit_days)
        # Iterate minute by minute but skip whole days/hours for speed.
        while local <= deadline:
            if local.month not in self.months or not self._day_matches(local):
                local = (local + timedelta(days=1)).replace(hour=0, minute=0)
                continue
            if local.hour not in self.hours:
                local = (local + timedelta(hours=1)).replace(minute=0)
                continue
            if local.minute not in self.minutes:
                local += timedelta(minutes=1)
                continue
            return local.astimezone(timezone.utc)
        return None


def get_zone(name: str | None) -> ZoneInfo | timezone:
    if not name or name.upper() == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def compute_next_run(
    schedule_type: str,
    *,
    interval_value: int = 1,
    hour: int = 3,
    minute: int = 0,
    day_of_week: int = 1,
    day_of_month: int = 1,
    cron_expression: str = "",
    timezone_name: str = "UTC",
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    paused: bool = False,
    now: datetime | None = None,
) -> datetime | None:
    """Compute the next UTC run time for a schedule definition."""
    if paused or schedule_type == "manual":
        return None
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    tz = get_zone(timezone_name)

    if start_date is not None and start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    if end_date is not None and end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)

    base = now
    if start_date and start_date > base:
        base = start_date - timedelta(seconds=1)

    nxt: datetime | None = None

    if schedule_type == "minutes":
        step = max(1, int(interval_value or 1))
        nxt = base + timedelta(minutes=step)
    elif schedule_type == "hourly":
        step = max(1, int(interval_value or 1))
        local = base.astimezone(tz)
        candidate = local.replace(minute=int(minute or 0), second=0, microsecond=0)
        while candidate <= local:
            candidate += timedelta(hours=step)
        nxt = candidate.astimezone(timezone.utc)
    elif schedule_type in {"daily", "weekly", "monthly"}:
        local = base.astimezone(tz)
        candidate = local.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
        if schedule_type == "daily":
            if candidate <= local:
                candidate += timedelta(days=1)
        elif schedule_type == "weekly":
            # day_of_week uses cron convention 0=Sunday
            target_py = (int(day_of_week) - 1) % 7  # Monday=0
            days_ahead = (target_py - candidate.weekday()) % 7
            candidate += timedelta(days=days_ahead)
            if candidate <= local:
                candidate += timedelta(days=7)
        else:
            dom = max(1, min(31, int(day_of_month)))
            year, month = candidate.year, candidate.month
            for _ in range(60):
                try:
                    candidate = candidate.replace(year=year, month=month, day=dom)
                except ValueError:
                    # Month has fewer days: clamp to last day
                    import calendar
                    last = calendar.monthrange(year, month)[1]
                    candidate = candidate.replace(year=year, month=month, day=last)
                if candidate > local:
                    break
                month += 1
                if month > 12:
                    month = 1
                    year += 1
                candidate = candidate.replace(year=year, month=month, day=1)
                import calendar
                last = calendar.monthrange(year, month)[1]
                candidate = candidate.replace(day=min(dom, last))
        nxt = candidate.astimezone(timezone.utc)
    elif schedule_type == "cron":
        if not cron_expression.strip():
            return None
        nxt = CronExpression(cron_expression).next_after(base, tz)
    else:
        return None

    if nxt is None:
        return None
    if start_date and nxt < start_date:
        nxt = start_date
    if end_date and nxt > end_date:
        return None
    return nxt


def describe_schedule(
    schedule_type: str,
    *,
    interval_value: int = 1,
    hour: int = 3,
    minute: int = 0,
    day_of_week: int = 1,
    day_of_month: int = 1,
    cron_expression: str = "",
) -> str:
    dow_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    hhmm = f"{int(hour):02d}:{int(minute):02d}"
    if schedule_type == "manual":
        return "Manual only"
    if schedule_type == "minutes":
        return f"Every {interval_value} minute(s)"
    if schedule_type == "hourly":
        return f"Every {interval_value} hour(s) at minute {int(minute):02d}"
    if schedule_type == "daily":
        return f"Daily at {hhmm}"
    if schedule_type == "weekly":
        return f"Weekly on {dow_names[int(day_of_week) % 7]} at {hhmm}"
    if schedule_type == "monthly":
        return f"Monthly on day {int(day_of_month)} at {hhmm}"
    if schedule_type == "cron":
        return f"Cron: {cron_expression}"
    return "Unknown"
