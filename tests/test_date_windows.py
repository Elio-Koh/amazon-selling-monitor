from datetime import date

from src.date_windows import resolve_date_window


def test_resolve_today_uses_anchor_date():
    window = resolve_date_window("Today", anchor_date=date(2026, 6, 12))

    assert window.start_date == "2026-06-12"
    assert window.end_date == "2026-06-12"
    assert window.label == "Today"
    assert window.is_partial is True


def test_resolve_yesterday_uses_previous_day():
    window = resolve_date_window("Yesterday", anchor_date=date(2026, 6, 12))

    assert window.start_date == "2026-06-11"
    assert window.end_date == "2026-06-11"
    assert window.label == "Yesterday"
    assert window.is_partial is False


def test_resolve_last_7_days_includes_anchor_end_date():
    window = resolve_date_window("Last 7 Days", anchor_date=date(2026, 6, 12))

    assert window.start_date == "2026-06-06"
    assert window.end_date == "2026-06-12"
    assert window.days == 7


def test_resolve_custom_requires_dates():
    window = resolve_date_window(
        "Custom",
        anchor_date=date(2026, 6, 12),
        custom_start=date(2026, 6, 1),
        custom_end=date(2026, 6, 10),
    )

    assert window.start_date == "2026-06-01"
    assert window.end_date == "2026-06-10"
    assert window.label == "Jun 1 - Jun 10"
