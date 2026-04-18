"""Parse one JSONL line from audit.log into a row dict."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

VALID_EVENTS = {"tool_call", "pipeline_stage", "audit_summary"}


def parse_iso_to_epoch_ms(ts: str) -> int:
    """Parse an ISO-8601 timestamp written by src/observability/audit.py.

    audit.py writes naive ISO strings via:
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    Example: "2026-04-18T12:00:00.123" with NO timezone suffix.
    Naive timestamps MUST be treated as UTC.
    """
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise ValueError(f"Invalid ISO timestamp: {ts!r}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def parse_line(line: str) -> dict | None:
    """Parse a single JSONL line into a row dict, or None if malformed.

    Returns dict with keys matching the events table columns:
      ts_ms, trace_id, event, duration_ms, status, slow,
      tool, stage, interface, payload_json
    """
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as e:
        log.warning("Skipping malformed JSON line: %s", e)
        return None
    if not isinstance(obj, dict):
        log.warning("Skipping non-object JSON: %r", obj)
        return None

    ts_raw = obj.get("timestamp")
    if not ts_raw:
        log.warning("Skipping line with no timestamp")
        return None
    try:
        ts_ms = parse_iso_to_epoch_ms(ts_raw)
    except ValueError as e:
        log.warning("Skipping line with bad timestamp: %s", e)
        return None

    event = obj.get("event") or "unknown"
    # audit_summary events have no trace context — store empty string (NOT NULL).
    trace_id = obj.get("trace_id") or ""

    return {
        "ts_ms": ts_ms,
        "trace_id": trace_id,
        "event": event,
        "duration_ms": float(obj.get("duration_ms") or 0),
        "status": obj.get("status") or "ok",
        "slow": 1 if obj.get("slow") else 0,
        "tool": obj.get("tool") if event == "tool_call" else None,
        "stage": obj.get("stage") if event == "pipeline_stage" else None,
        "interface": obj.get("interface"),
        "payload_json": line,
    }
