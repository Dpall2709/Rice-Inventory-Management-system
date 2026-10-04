"""
Quick period buttons for list filters (Today, This month, ... All time) and
safe reading of ?from= / ?to= dates, shared by every list page.
"""

from datetime import date, timedelta

from django.utils.translation import gettext as _


def parse_date(value):
    """A date from ?from=YYYY-MM-DD, or None for empty / mistyped values."""
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def date_range(params):
    """(from, to) from the query string; swapped into order when typed backwards."""
    start, end = parse_date(params.get("from")), parse_date(params.get("to"))
    if start and end and start > end:
        start, end = end, start
    return start, end


def period_chips(today, date_from, date_to):
    """Buttons that fill the From / To boxes. "All time" leaves both empty."""
    month_start = today.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    chips = [
        (_("Today"), today, today),
        (_("This month"), month_start, today),
        (_("Last month"), last_month_end.replace(day=1), last_month_end),
        (_("Last 3 months"), today - timedelta(days=90), today),
        (_("This year"), today.replace(month=1, day=1), today),
        (_("All time"), None, None),
    ]
    return [
        {"label": label, "from": start, "to": end, "active": (start, end) == (date_from, date_to)}
        for label, start, end in chips
    ]
