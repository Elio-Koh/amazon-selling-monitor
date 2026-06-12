"""Date-window helpers for dashboard data pulls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional


PRESETS = ("Today", "Yesterday", "Last 7 Days", "Last 14 Days", "Last 30 Days", "Custom")


@dataclass(frozen=True)
class DateWindow:
    preset: str
    start_date: str
    end_date: str
    label: str
    days: int
    is_partial: bool = False


def today_for_timezone(timezone_name: str = "Asia/Shanghai") -> date:
    if timezone_name == "Asia/Shanghai":
        return datetime.now(timezone(timedelta(hours=8))).date()
    return datetime.now(timezone.utc).date()


def resolve_date_window(
    preset: str,
    *,
    anchor_date: Optional[date] = None,
    custom_start: Optional[date] = None,
    custom_end: Optional[date] = None,
) -> DateWindow:
    anchor = anchor_date or today_for_timezone()
    normalized = preset if preset in PRESETS else "Yesterday"

    if normalized == "Today":
        return _window(normalized, anchor, anchor, "Today", is_partial=True)
    if normalized == "Yesterday":
        day = anchor - timedelta(days=1)
        return _window(normalized, day, day, "Yesterday")
    if normalized == "Last 7 Days":
        return _rolling_window(normalized, anchor, 7)
    if normalized == "Last 14 Days":
        return _rolling_window(normalized, anchor, 14)
    if normalized == "Last 30 Days":
        return _rolling_window(normalized, anchor, 30)

    if custom_start is None or custom_end is None:
        raise ValueError("Custom date window requires start and end dates.")
    if custom_start > custom_end:
        raise ValueError("Custom start date cannot be after end date.")
    return _window(normalized, custom_start, custom_end, _format_range_label(custom_start, custom_end))


def _rolling_window(preset: str, end: date, days: int) -> DateWindow:
    start = end - timedelta(days=days - 1)
    return _window(preset, start, end, preset)


def _window(preset: str, start: date, end: date, label: str, *, is_partial: bool = False) -> DateWindow:
    return DateWindow(
        preset=preset,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        label=label,
        days=(end - start).days + 1,
        is_partial=is_partial,
    )


def _format_range_label(start: date, end: date) -> str:
    if start.year == end.year:
        return f"{start.strftime('%b')} {start.day} - {end.strftime('%b')} {end.day}"
    return f"{start.strftime('%b')} {start.day}, {start.year} - {end.strftime('%b')} {end.day}, {end.year}"
