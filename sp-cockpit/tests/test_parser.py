"""AC13: parser handles naive ISO timestamps as UTC."""
from datetime import datetime, timezone

import pytest

from sp_cockpit.parser import parse_iso_to_epoch_ms, parse_line


def test_naive_iso_treated_as_utc():
    naive = "2026-04-18T12:00:00.123"
    z_form = "2026-04-18T12:00:00.123Z"
    expected = int(datetime(2026, 4, 18, 12, 0, 0, 123000, tzinfo=timezone.utc).timestamp() * 1000)
    assert parse_iso_to_epoch_ms(naive) == expected
    assert parse_iso_to_epoch_ms(z_form) == expected


def test_offset_iso_preserved():
    s = "2026-04-18T12:00:00.123+02:00"
    expected = int(datetime.fromisoformat(s).timestamp() * 1000)
    assert parse_iso_to_epoch_ms(s) == expected


def test_invalid_iso_raises():
    with pytest.raises(ValueError):
        parse_iso_to_epoch_ms("not-a-date")


def test_parse_tool_call_line():
    line = '{"timestamp":"2026-04-18T12:00:00.000","trace_id":"abc","event":"tool_call","duration_ms":12.5,"status":"ok","slow":false,"tool":"search_code","interface":"mcp"}'
    row = parse_line(line)
    assert row is not None
    assert row["trace_id"] == "abc"
    assert row["event"] == "tool_call"
    assert row["tool"] == "search_code"
    assert row["interface"] == "mcp"
    assert row["duration_ms"] == 12.5
    assert row["payload_json"].startswith("{")


def test_parse_audit_summary_empty_trace_id():
    """audit_summary events have no trace context — store empty string, not NULL."""
    line = '{"timestamp":"2026-04-18T12:00:00.000","event":"audit_summary","duration_ms":0,"status":"ok","slow":false}'
    row = parse_line(line)
    assert row is not None
    assert row["trace_id"] == ""
    assert row["event"] == "audit_summary"
    assert row["tool"] is None
    assert row["stage"] is None


def test_parse_pipeline_stage_line():
    line = '{"timestamp":"2026-04-18T12:00:00.000","trace_id":"x","event":"pipeline_stage","duration_ms":5,"status":"ok","slow":false,"stage":"classify"}'
    row = parse_line(line)
    assert row is not None
    assert row["stage"] == "classify"
    assert row["tool"] is None


def test_parse_rejects_malformed():
    assert parse_line("not json") is None
    assert parse_line("") is None
    assert parse_line("   ") is None


def test_parse_rejects_missing_timestamp():
    line = '{"event":"tool_call","trace_id":"x"}'
    assert parse_line(line) is None
