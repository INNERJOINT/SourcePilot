"""
Audit log module tests

Tests core functionality of audit.py: JSON formatting, timing, error handling,
slow-query flagging, toggle control, propagate isolation, and stats aggregation.
"""

import asyncio
import json
import logging
import os
import sys
import tempfile

import pytest

from observability.audit import (
    AuditContext,
    AuditStats,
    JsonFormatter,
    _NonBlockingQueueHandler,
    _truncate,
    audit_tool_call,
    audit_stage,
    extract_result_count,
    new_trace_id,
    get_trace_id,
    reset_audit_logger,
    setup_audit_logger,
    start_audit_listener,
    stop_audit_listener,
)
import config


# ─── Fixtures ─────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_audit():
    """Reset audit logger and config before and after each test."""
    reset_audit_logger()
    # Save original values
    orig_enabled = config.AUDIT_ENABLED
    orig_slow_ms = config.AUDIT_SLOW_QUERY_MS
    orig_log_file = config.AUDIT_LOG_FILE
    yield
    # restore
    reset_audit_logger()
    config.AUDIT_ENABLED = orig_enabled
    config.AUDIT_SLOW_QUERY_MS = orig_slow_ms
    config.AUDIT_LOG_FILE = orig_log_file


class LogCapture(logging.Handler):
    """Captures log records for assertions."""

    def __init__(self):
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord):
        self.records.append(self.format(record))


def _setup_with_capture() -> LogCapture:
    """Set up audit logger and attach an in-memory capture handler."""
    config.AUDIT_ENABLED = True
    config.AUDIT_LOG_FILE = ""  # don't write to file
    logger = setup_audit_logger("http")  # http mode → stderr handler
    # attach a capture handler
    capture = LogCapture()
    capture.setFormatter(JsonFormatter())
    logger.addHandler(capture)
    return capture


# ─── Tests ────────────────────────────────────────────

class TestJsonFormat:
    """Test 1: JSON validity + required fields."""

    @pytest.mark.asyncio
    async def test_json_format(self):
        capture = _setup_with_capture()

        async with audit_tool_call("search_code", {"query": "test"}, "mcp") as ctx:
            ctx.set_result_count(5)

        assert len(capture.records) == 1
        data = json.loads(capture.records[0])

        # Required fields check
        assert "timestamp" in data
        assert data["event"] == "tool_call"
        assert data["interface"] == "mcp"
        assert data["tool"] == "search_code"
        assert data["arguments"] == {"query": "test"}
        assert isinstance(data["duration_ms"], (int, float))
        assert data["result_count"] == 5
        assert data["status"] == "ok"
        assert data["slow"] is False


class TestDurationRecorded:
    """Test 2: duration_ms > 0."""

    @pytest.mark.asyncio
    async def test_duration_recorded(self):
        capture = _setup_with_capture()

        async with audit_tool_call("search_symbol", {"symbol": "Foo"}, "mcp") as ctx:
            await asyncio.sleep(0.01)  # ensure measurable elapsed time
            ctx.set_result_count(1)

        data = json.loads(capture.records[0])
        assert data["duration_ms"] > 0


class TestErrorStatus:
    """Test 3: status='error' + error_message when an exception is raised."""

    @pytest.mark.asyncio
    async def test_error_status(self):
        capture = _setup_with_capture()

        with pytest.raises(ValueError, match="test error"):
            async with audit_tool_call("search_file", {"path": "x"}, "mcp") as ctx:
                raise ValueError("test error")

        data = json.loads(capture.records[0])
        assert data["status"] == "error"
        assert data["error_message"] == "test error"
        assert isinstance(data["duration_ms"], (int, float))


class TestSlowQueryFlag:
    """Test 4: slow=true when threshold is exceeded."""

    @pytest.mark.asyncio
    async def test_slow_query_flag(self):
        capture = _setup_with_capture()
        config.AUDIT_SLOW_QUERY_MS = 10  # 10ms threshold

        async with audit_tool_call("search_regex", {"pattern": ".*"}, "mcp") as ctx:
            await asyncio.sleep(0.02)  # 20ms > 10ms threshold
            ctx.set_result_count(3)

        data = json.loads(capture.records[0])
        assert data["slow"] is True
        assert data["duration_ms"] > 10


class TestAuditDisabled:
    """Test 5: No audit output when AUDIT_ENABLED=false."""

    @pytest.mark.asyncio
    async def test_audit_disabled(self):
        config.AUDIT_ENABLED = False
        logger = setup_audit_logger("http")

        capture = LogCapture()
        capture.setFormatter(JsonFormatter())
        logger.addHandler(capture)

        async with audit_tool_call("search_code", {"query": "test"}, "mcp") as ctx:
            ctx.set_result_count(1)

        assert len(capture.records) == 0


class TestPropagateFalse:
    """Test 6: audit logger does not propagate to root logger."""

    @pytest.mark.asyncio
    async def test_propagate_false(self):
        _setup_with_capture()

        # attach a capture to the root logger
        root_capture = LogCapture()
        root_capture.setFormatter(logging.Formatter("%(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(root_capture)

        try:
            async with audit_tool_call("list_repos", {"query": ""}, "mcp") as ctx:
                ctx.set_result_count(10)

            # root logger must not receive any audit records
            audit_in_root = [r for r in root_capture.records if "tool_call" in r]
            assert len(audit_in_root) == 0
        finally:
            root_logger.removeHandler(root_capture)


class TestStatsSummary:
    """Test 7: AuditStats accumulates correctly."""

    def test_stats_aggregation(self):
        config.AUDIT_ENABLED = True
        stats = AuditStats()

        stats.record("search_code", 100.0, False, False)
        stats.record("search_code", 200.0, False, False)
        stats.record("search_symbol", 3500.0, False, True)
        stats.record("list_repos", 50.0, True, False)

        summary = stats.summary()
        assert summary["total_calls"] == 4
        assert summary["total_errors"] == 1
        assert summary["slow_queries"] == 1
        assert summary["per_tool"]["search_code"]["count"] == 2
        assert summary["per_tool"]["search_code"]["avg_ms"] == 150.0
        assert summary["per_tool"]["search_symbol"]["count"] == 1
        assert summary["per_tool"]["list_repos"]["count"] == 1

    def test_stats_reset(self):
        config.AUDIT_ENABLED = True
        stats = AuditStats()
        stats.record("search_code", 100.0, False, False)
        stats.reset()

        summary = stats.summary()
        assert summary["total_calls"] == 0
        assert summary["per_tool"] == {}


class TestExtractResultCount:
    """Tests for the extract_result_count helper function."""

    def test_search_results(self):
        text = 'Found 10 results matching "test":\n'
        assert extract_result_count("search_code", text) == 10

    def test_list_repos(self):
        text = "Found 5 repositories:\n"
        assert extract_result_count("list_repos", text) == 5

    def test_get_file_content(self):
        text = "# repo/file (L1-L100 / 100 lines total)"
        assert extract_result_count("get_file_content", text) == 1

    def test_read_resource(self):
        text = "# repo/file (200 lines total)"
        assert extract_result_count("read_resource", text) == 1

    def test_no_match(self):
        assert extract_result_count("search_code", "No code found matching the query.") is None


class TestAuditLogFile:
    """Test audit log writing to file (via QueueListener)."""

    @pytest.mark.asyncio
    async def test_file_handler(self):
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            log_path = f.name

        try:
            config.AUDIT_ENABLED = True
            config.AUDIT_LOG_FILE = log_path
            setup_audit_logger("stdio")
            start_audit_listener()

            async with audit_tool_call("search_code", {"query": "file_test"}, "mcp") as ctx:
                ctx.set_result_count(3)

            # Give the QueueListener background thread time to process the record
            await asyncio.sleep(0.1)
            stop_audit_listener()

            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            assert len(lines) >= 1
            data = json.loads(lines[0])
            assert data["tool"] == "search_code"
            assert data["result_count"] == 3
        finally:
            os.unlink(log_path)


class TestTraceId:
    """Tests for trace_id generation and propagation."""

    def test_new_trace_id_format(self):
        """trace_id is a 32-character hex string."""
        tid = new_trace_id()
        assert len(tid) == 32
        assert all(c in "0123456789abcdef" for c in tid)

    def test_get_trace_id_returns_current(self):
        """get_trace_id returns the value most recently set by new_trace_id."""
        tid = new_trace_id()
        assert get_trace_id() == tid

    @pytest.mark.asyncio
    async def test_trace_id_in_tool_call_log(self):
        """audit_tool_call log records contain the current trace_id."""
        capture = _setup_with_capture()
        tid = new_trace_id()

        async with audit_tool_call("search_code", {"query": "test"}, "mcp") as ctx:
            ctx.set_result_count(1)

        data = json.loads(capture.records[0])
        assert data["trace_id"] == tid


class TestAuditStage:
    """Tests for the audit_stage context manager."""

    @pytest.mark.asyncio
    async def test_stage_basic(self):
        """audit_stage records contain stage, stage_args, and stage_result."""
        capture = _setup_with_capture()
        new_trace_id()

        async with audit_stage("classify", {"query": "test"}) as stg:
            stg.set_result({"query_type": "exact"})

        data = json.loads(capture.records[0])
        assert data["event"] == "pipeline_stage"
        assert data["stage"] == "classify"
        assert data["stage_result"]["query_type"] == "exact"
        assert data["stage_args"]["query"] == "test"
        assert data["duration_ms"] >= 0
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_stage_result_not_truncated(self):
        """pipeline_stage stage_result is no longer subject to _truncate limits;
        the records array is written as-is even if a single record exceeds the 1KB default threshold."""
        capture = _setup_with_capture()
        new_trace_id()

        big_records = [
            {"file": f"src/file_{i}.py", "line": i, "score": 0.9,
             "snippet": "X" * 200}
            for i in range(20)
        ]

        async with audit_stage("zoekt_search", {"query": "test"}) as stg:
            stg.set_result({"records_count": len(big_records), "records": big_records})

        data = json.loads(capture.records[0])
        assert data["event"] == "pipeline_stage"
        assert "stage_result_truncated" not in data
        assert data["stage_result"]["records_count"] == 20
        assert isinstance(data["stage_result"]["records"], list)
        assert len(data["stage_result"]["records"]) == 20
        assert data["stage_result"]["records"][0]["file"] == "src/file_0.py"
        assert data["stage_result"]["records"][19]["snippet"] == "X" * 200

    @pytest.mark.asyncio
    async def test_stage_error(self):
        """audit_stage records an error when an exception is raised."""
        capture = _setup_with_capture()
        new_trace_id()

        with pytest.raises(ValueError):
            async with audit_stage("rewrite", {"query": "test"}) as stg:
                raise ValueError("LLM timeout")

        data = json.loads(capture.records[0])
        assert data["status"] == "error"
        assert data["error_message"] == "LLM timeout"

    @pytest.mark.asyncio
    async def test_stage_shares_trace_id(self):
        """Multiple stages within the same request share the same trace_id."""
        capture = _setup_with_capture()
        tid = new_trace_id()

        async with audit_stage("classify", {}) as stg:
            stg.set_result({"query_type": "natural_language"})

        async with audit_stage("rewrite", {}) as stg:
            stg.set_result({"method": "llm"})

        assert len(capture.records) == 2
        data1 = json.loads(capture.records[0])
        data2 = json.loads(capture.records[1])
        assert data1["trace_id"] == tid
        assert data2["trace_id"] == tid

    @pytest.mark.asyncio
    async def test_stage_disabled(self):
        """No output from audit_stage when AUDIT_ENABLED=false."""
        config.AUDIT_ENABLED = False
        reset_audit_logger()
        logger = setup_audit_logger("http")
        capture = LogCapture()
        capture.setFormatter(JsonFormatter())
        logger.addHandler(capture)

        async with audit_stage("classify", {"query": "test"}) as stg:
            stg.set_result({"query_type": "exact"})

        assert len(capture.records) == 0


# ─── Additional tests ─────────────────────────────────


class TestAuditStatsEnhanced:
    """Tests for enhanced AuditStats: per-tool error counts, reservoir sampling, and percentiles."""

    def test_per_tool_error_count(self):
        config.AUDIT_ENABLED = True
        stats = AuditStats()
        stats.record("search_code", 100.0, True, False)
        stats.record("search_code", 200.0, False, False)
        stats.record("search_symbol", 50.0, True, False)

        summary = stats.summary()
        assert summary["per_tool"]["search_code"]["errors"] == 1
        assert summary["per_tool"]["search_code"]["error_rate"] == 0.5
        assert summary["per_tool"]["search_symbol"]["errors"] == 1
        assert summary["per_tool"]["search_symbol"]["error_rate"] == 1.0

    def test_percentile_computation(self):
        config.AUDIT_ENABLED = True
        stats = AuditStats()
        for i in range(1, 101):
            stats.record("test_tool", float(i), False, False)

        summary = stats.summary()
        tool = summary["per_tool"]["test_tool"]
        # 100 values: 1.0..100.0; index 50/100=50 → value 51.0
        assert tool["p50_ms"] == 51.0
        assert tool["p95_ms"] == 96.0
        assert tool["p99_ms"] == 100.0

    def test_percentile_single_sample(self):
        """p99 with <2 samples should not crash."""
        config.AUDIT_ENABLED = True
        stats = AuditStats()
        stats.record("t", 42.0, False, False)

        summary = stats.summary()
        assert summary["per_tool"]["t"]["p50_ms"] == 42.0
        assert summary["per_tool"]["t"]["p99_ms"] == 42.0

    def test_percentile_empty(self):
        result = AuditStats._compute_percentiles([])
        assert result == {"p50_ms": 0, "p95_ms": 0, "p99_ms": 0}


class TestReservoirSampling:
    """Tests for reservoir sampling properties."""

    def test_reservoir_capped_at_size(self):
        config.AUDIT_ENABLED = True
        stats = AuditStats()
        for i in range(2000):
            stats.record("tool", float(i), False, False)

        assert len(stats._latency_reservoir["tool"]) == AuditStats.RESERVOIR_SIZE

    def test_reservoir_all_values_when_under_size(self):
        config.AUDIT_ENABLED = True
        stats = AuditStats()
        for i in range(50):
            stats.record("tool", float(i), False, False)

        assert len(stats._latency_reservoir["tool"]) == 50


class TestSummaryHistory:
    """Tests for the trend history ring buffer."""

    def test_trend_returns_snapshots(self):
        config.AUDIT_ENABLED = True
        stats = AuditStats()
        stats.record("t", 10.0, False, False)
        stats.log_summary()
        stats.record("t", 20.0, False, False)
        stats.log_summary()

        trend = stats.trend()
        assert len(trend) == 2
        assert trend[0]["per_tool"]["t"]["avg_ms"] == 10.0
        assert trend[1]["per_tool"]["t"]["avg_ms"] == 20.0

    def test_reset_preserves_history(self):
        config.AUDIT_ENABLED = True
        stats = AuditStats()
        stats.record("t", 10.0, False, False)
        stats.log_summary()
        stats.reset()

        assert len(stats.trend()) == 1
        assert stats.total_calls == 0

    def test_ring_buffer_capped(self):
        config.AUDIT_ENABLED = True
        stats = AuditStats()
        for i in range(20):
            stats.record("t", float(i), False, False)
            stats.log_summary()

        assert len(stats.trend()) == AuditStats.HISTORY_SIZE


class TestJsonFormatterSchema:
    """Tests for the different schemas of tool_call and pipeline_stage."""

    @pytest.mark.asyncio
    async def test_tool_call_has_interface_tool_arguments(self):
        capture = _setup_with_capture()
        async with audit_tool_call("search_code", {"query": "q"}, "mcp") as ctx:
            ctx.set_result_count(1)
        data = json.loads(capture.records[0])
        assert "interface" in data
        assert "tool" in data
        assert "arguments" in data
        assert "result_count" in data
        assert "stage" not in data
        assert "stage_args" not in data
        assert "stage_result" not in data

    @pytest.mark.asyncio
    async def test_pipeline_stage_has_stage_fields(self):
        capture = _setup_with_capture()
        new_trace_id()
        async with audit_stage("classify", {"query": "q"}) as stg:
            stg.set_result({"ok": True})
        data = json.loads(capture.records[0])
        assert "stage" in data
        assert "stage_args" in data
        assert "stage_result" in data
        assert "interface" not in data
        assert "tool" not in data
        assert "arguments" not in data


class TestTruncation:
    """Tests for large-field truncation protection."""

    def test_truncate_small_value(self):
        val, truncated = _truncate({"key": "short"})
        assert truncated is False
        assert val == {"key": "short"}

    def test_truncate_large_value(self):
        big = {"data": "x" * 2000}
        val, truncated = _truncate(big, max_bytes=100)
        assert truncated is True
        assert isinstance(val, str)
        assert len(val) <= 104

    @pytest.mark.asyncio
    async def test_large_arguments_truncated_in_log(self):
        capture = _setup_with_capture()
        big_args = {"query": "x" * 2000}
        async with audit_tool_call("search_code", big_args, "mcp") as ctx:
            ctx.set_result_count(1)
        data = json.loads(capture.records[0])
        assert data.get("arguments_truncated") is True

    @pytest.mark.asyncio
    async def test_large_stage_result_not_truncated(self):
        """New policy: pipeline_stage no longer truncates stage_result;
        even when serialized size far exceeds the _truncate default 1KB, it should be written as-is."""
        capture = _setup_with_capture()
        new_trace_id()
        async with audit_stage("rewrite", {"query": "q"}) as stg:
            stg.set_result({"queries": ["x" * 500 for _ in range(10)]})
        data = json.loads(capture.records[0])
        assert "stage_result_truncated" not in data
        assert len(data["stage_result"]["queries"]) == 10
        assert data["stage_result"]["queries"][0] == "x" * 500


class TestQueueHandler:
    """Tests for QueueHandler integration."""

    def test_logger_uses_non_blocking_handler(self):
        config.AUDIT_ENABLED = True
        config.AUDIT_LOG_FILE = ""
        reset_audit_logger()
        logger = setup_audit_logger("http")
        handlers = [h for h in logger.handlers if isinstance(h, _NonBlockingQueueHandler)]
        assert len(handlers) == 1


class TestQueueDropOnFull:
    """Tests for silent drop when queue is full."""

    def test_drop_on_full(self):
        import queue as queue_mod
        q = queue_mod.Queue(maxsize=2)
        handler = _NonBlockingQueueHandler(q)

        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        handler.enqueue(record)
        handler.enqueue(record)
        handler.enqueue(record)
        assert handler.dropped_count == 1
        assert q.qsize() == 2


class TestAuditStageRecord:
    """Tests that audit_stage feeds metrics into AuditStats."""

    @pytest.mark.asyncio
    async def test_stage_feeds_audit_stats(self):
        _setup_with_capture()
        config.AUDIT_ENABLED = True
        from observability.audit import audit_stats
        audit_stats.reset()
        new_trace_id()

        async with audit_stage("classify", {"query": "test"}) as stg:
            stg.set_result({"query_type": "exact"})

        assert audit_stats.total_calls >= 1
        assert "classify" in audit_stats._per_tool
