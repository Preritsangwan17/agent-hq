"""UTC time helpers. Storage is always ISO-8601 UTC with a trailing Z."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def now_iso() -> str:
    return to_iso(utcnow())


def iso_in(seconds: float) -> str:
    return to_iso(utcnow() + timedelta(seconds=seconds))


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def today_ist() -> date:
    return datetime.now(IST).date()


def next_midnight_ist_iso() -> str:
    now = datetime.now(IST)
    midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=IST)
    return to_iso(midnight)
