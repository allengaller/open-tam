from datetime import datetime, timezone

from open_tam.timeutil import parse_iso_local


def test_parses_naive_unchanged():
    dt = parse_iso_local("2026-08-29T00:05:00")
    assert dt.tzinfo is None
    assert dt == datetime(2026, 8, 29, 0, 5, 0)


def test_parses_utc_suffix_to_local_naive():
    aware = datetime(2026, 8, 29, 0, 5, 0, tzinfo=timezone.utc)
    expected = aware.astimezone().replace(tzinfo=None)
    assert parse_iso_local("2026-08-29T00:05:00Z") == expected
    assert parse_iso_local("2026-08-29T00:05:00+00:00") == expected
