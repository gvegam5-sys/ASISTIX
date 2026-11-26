from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


REPORTING_ZONE = ZoneInfo('America/Guayaquil')


def reporting_date(utc_value: datetime) -> date:
    """Interpret a timestamp from the database as UTC before taking its local date."""
    return utc_value.replace(tzinfo=timezone.utc).astimezone(REPORTING_ZONE).date()


def reporting_day_bounds(day: date) -> tuple[datetime, datetime]:
    """Return the half-open day bounds as UTC values for the database columns."""
    start = datetime.combine(day, time.min, REPORTING_ZONE)
    end = datetime.combine(day + timedelta(days=1), time.min, REPORTING_ZONE)
    return (
        start.astimezone(timezone.utc).replace(tzinfo=None),
        end.astimezone(timezone.utc).replace(tzinfo=None),
    )
