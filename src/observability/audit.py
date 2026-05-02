"""
Audit logging module

Provides structured JSON audit logs that record detailed information about each tool call
(latency, result count, status, etc.) to support performance tuning and operational monitoring.

Usage:
    from observability.audit import setup_audit_logger, audit_tool_call, audit_stats

    setup_audit_logger("stdio")  # or "http"

    async with audit_tool_call("search_code", {"query": "foo"}, "mcp") as ctx:
        results = await do_search()
        ctx.set_result_count(len(results))
"""

import asyncio
import json
import logging
import os
import queue
import random
import re
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler

import config


# ─── Request-scoped trace_id ───────────────────────────────────────────
# TODO: extract trace_id management to observability/tracing.py when OTel/spans are added

_trace_id: ContextVar[str] = ContextVar("audit_trace_id", default="")


def new_trace_id() -> str:
    """Generate a new trace_id, set it on the current context, and return it."""
    tid = uuid.uuid4().hex
    _trace_id.set(tid)
    return tid


def get_trace_id() -> str:
    """Return the trace_id for the current context (empty string if none)."""
    return _trace_id.get()


# ─── JSON formatter ──────────────────────────────────────


def _truncate(obj, max_bytes: int = 1024) -> tuple:
    """Serialize to JSON and truncate if over max_bytes; returns (value, truncated_flag)."""
    try:
        serialized = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        serialized = str(obj)
    if len(serialized.encode("utf-8")) <= max_bytes:
        return obj, False
    return serialized[:max_bytes] + "...", True


class JsonFormatter(logging.Formatter):
    """Format a LogRecord as single-line JSON, using different schemas per event type."""

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event", "unknown")

        # Common fields
        data: dict = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
            "trace_id": getattr(record, "trace_id", "") or get_trace_id(),
            "event": event,
            "duration_ms": getattr(record, "duration_ms", 0),
            "status": getattr(record, "status", "ok"),
            "slow": getattr(record, "slow", False),
        }

        if event == "tool_call":
            args_val = getattr(record, "arguments", {})
            args_val, args_truncated = _truncate(args_val)
            data["interface"] = getattr(record, "interface", "")
            data["tool"] = getattr(record, "tool", "")
            data["arguments"] = args_val
            if args_truncated:
                data["arguments_truncated"] = True
            data["result_count"] = getattr(record, "result_count", None)

        elif event == "pipeline_stage":
            data["stage"] = getattr(record, "stage", "")
            data["stage_args"] = getattr(record, "stage_args", {})
            # User decision: pipeline_stage is not truncated — keep full records array for auditing
            data["stage_result"] = getattr(record, "stage_result", {})

        elif event == "audit_summary":
            extra_fields = getattr(record, "extra_fields", None)
            if extra_fields:
                data.update(extra_fields)

        error_message = getattr(record, "error_message", None)
        if error_message:
            data["error_message"] = error_message

        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


# ─── Non-blocking queue handler ──────────────────────────────────────

class _NonBlockingQueueHandler(QueueHandler):
    """QueueHandler subclass: silently drops records when the queue is full, never blocks the event loop."""  # noqa: E501

    def __init__(self, q: queue.Queue):
        super().__init__(q)
        self.dropped_count = 0

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            self.dropped_count += 1


# ─── Audit logger setup ───────────────────────────────────

_audit_logger: logging.Logger | None = None
_queue_listener: QueueListener | None = None
_queue_handler: _NonBlockingQueueHandler | None = None


def setup_audit_logger(transport_mode: str = "stdio") -> logging.Logger:
    """Initialize the dedicated audit logger.

    Args:
        transport_mode: "stdio" or "http".
            stdio: defaults to writing to a file (RotatingFileHandler) to avoid
                   polluting MCP JSON-RPC output.
            http: defaults to writing to stderr (StreamHandler).

    Returns:
        The configured audit logger.
    """
    global _audit_logger, _queue_listener, _queue_handler
    if _audit_logger is not None:
        return _audit_logger

    if not config.AUDIT_ENABLED:
        logger = logging.getLogger("audit")
        logger.propagate = False
        logger.addHandler(logging.NullHandler())
        logger.setLevel(logging.CRITICAL + 1)
        _audit_logger = logger
        return logger

    logger = logging.getLogger("audit")
    logger.propagate = False
    logger.setLevel(logging.INFO)

    formatter = JsonFormatter()

    # Determine the actual output destination
    log_file = config.AUDIT_LOG_FILE
    if not log_file and transport_mode == "stdio":
        log_file = "audit.log"

    if log_file:
        real_handler = RotatingFileHandler(
            log_file,
            maxBytes=50 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
    else:
        import sys
        real_handler = logging.StreamHandler(sys.stderr)

    real_handler.setFormatter(formatter)

    # Async-write via QueueHandler + QueueListener
    q: queue.Queue = queue.Queue(maxsize=10000)
    _queue_handler = _NonBlockingQueueHandler(q)
    _queue_listener = QueueListener(q, real_handler, respect_handler_level=True)
    logger.addHandler(_queue_handler)

    _audit_logger = logger
    return logger


def start_audit_listener():
    """Start the QueueListener background thread (called in the app lifespan)."""
    if _queue_listener is not None:
        _queue_listener.start()


def stop_audit_listener():
    """Stop the QueueListener background thread (called in the app lifespan)."""
    if _queue_listener is not None:
        _queue_listener.stop()


def get_audit_logger() -> logging.Logger | None:
    """Return the initialized audit logger (None if not yet initialized)."""
    return _audit_logger


def reset_audit_logger():
    """Reset the audit logger (for tests only)."""
    global _audit_logger, _queue_listener, _queue_handler
    if _queue_listener is not None:
        try:
            _queue_listener.stop()
        except Exception:
            pass
        _queue_listener = None
    _queue_handler = None
    if _audit_logger is not None:
        for h in _audit_logger.handlers[:]:
            _audit_logger.removeHandler(h)
            h.close()
        _audit_logger = None


# ─── Audit context managers ──────────────────────────────────────────

class AuditContext:
    """Audit context for a tool call or pipeline stage, used to collect result metadata."""

    def __init__(self):
        self.result_count: int | None = None
        self.error_message: str | None = None
        self.result: dict | None = None

    def set_result_count(self, count: int):
        self.result_count = count

    def set_error(self, message: str):
        self.error_message = message

    def set_result(self, result: dict):
        self.result = result


# Regex to extract result count from formatted text
_RESULT_COUNT_RE = re.compile(r"Found (\d+)")


def extract_result_count(tool_name: str, text: str) -> int | None:
    """Extract the result count from tool output text.

    - search_code/symbol/file/regex/list_repos: regex match for "Found N"
    - get_file_content/read_resource: hardcoded 1
    - returns None when the count cannot be extracted
    """
    if tool_name in ("get_file_content", "read_resource"):
        return 1

    match = _RESULT_COUNT_RE.search(text)
    if match:
        return int(match.group(1))
    return None


@asynccontextmanager
async def audit_tool_call(tool_name: str, arguments: dict, interface: str):
    """Async context manager for auditing a tool call.

    Usage:
        async with audit_tool_call("search_code", args, "mcp") as ctx:
            result = await do_work()
            ctx.set_result_count(10)
    """
    ctx = AuditContext()
    start = time.perf_counter()

    try:
        yield ctx
    except Exception as e:
        ctx.set_error(str(e))
        raise
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        slow = duration_ms > config.AUDIT_SLOW_QUERY_MS
        status = "error" if ctx.error_message else "ok"

        logger = get_audit_logger()
        if logger and logger.isEnabledFor(logging.INFO):
            logger.info(
                "",
                extra={
                    "event": "tool_call",
                    "trace_id": get_trace_id(),
                    "interface": interface,
                    "tool": tool_name,
                    "arguments": arguments,
                    "duration_ms": duration_ms,
                    "result_count": ctx.result_count,
                    "status": status,
                    "error_message": ctx.error_message,
                    "slow": slow,
                },
            )

        # Update statistics
        audit_stats.record(tool_name, duration_ms, status == "error", slow)


@asynccontextmanager
async def audit_stage(stage: str, metadata: dict | None = None):
    """Async context manager for auditing a pipeline stage.

    Args:
        stage: stage name (e.g. "classify", "rewrite", "zoekt_search", "rrf_merge", "rerank")
        metadata: stage input parameters/config (recorded in the log)

    Usage:
        async with audit_stage("classify", {"query": q}) as ctx:
            result = classify_query(q)
            ctx.set_result({"query_type": "natural_language"})
    """
    ctx = AuditContext()
    start = time.perf_counter()

    try:
        yield ctx
    except Exception as e:
        ctx.set_error(str(e))
        raise
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        status = "error" if ctx.error_message else "ok"
        slow = duration_ms > config.AUDIT_SLOW_QUERY_MS

        logger = get_audit_logger()
        if logger and logger.isEnabledFor(logging.INFO):
            logger.info(
                "",
                extra={
                    "event": "pipeline_stage",
                    "trace_id": get_trace_id(),
                    "stage": stage,
                    "stage_args": metadata or {},
                    "stage_result": ctx.result or {},
                    "duration_ms": duration_ms,
                    "result_count": ctx.result_count,
                    "status": status,
                    "error_message": ctx.error_message,
                    "slow": slow,
                },
            )

        # Include stage-level metrics in statistics
        audit_stats.record(stage, duration_ms, status == "error", slow)


# ─── Audit statistics ──────────────────────────────────────────────────

class AuditStats:
    """Lightweight audit statistics aggregator with per-tool error rates, percentile latencies, and trend history."""  # noqa: E501

    RESERVOIR_SIZE = 1000
    HISTORY_SIZE = 12  # number of period snapshots (default 5min × 12 = 1h)

    def __init__(self):
        self.total_calls = 0
        self.total_errors = 0
        self.slow_queries = 0
        self._per_tool: dict[str, dict] = {}
        self._latency_reservoir: dict[str, list[float]] = {}
        self._reservoir_n: dict[str, int] = {}  # total count for Algorithm R
        self._summary_history: list[dict] = []

    def record(self, tool: str, duration_ms: float, is_error: bool, is_slow: bool):
        if not config.AUDIT_ENABLED:
            return
        self.total_calls += 1
        if is_error:
            self.total_errors += 1
        if is_slow:
            self.slow_queries += 1

        if tool not in self._per_tool:
            self._per_tool[tool] = {"count": 0, "total_ms": 0.0, "errors": 0}
            self._latency_reservoir[tool] = []
            self._reservoir_n[tool] = 0
        self._per_tool[tool]["count"] += 1
        self._per_tool[tool]["total_ms"] += duration_ms
        if is_error:
            self._per_tool[tool]["errors"] += 1

        # Algorithm R reservoir sampling
        self._reservoir_n[tool] += 1
        n = self._reservoir_n[tool]
        reservoir = self._latency_reservoir[tool]
        if len(reservoir) < self.RESERVOIR_SIZE:
            reservoir.append(duration_ms)
        else:
            j = random.randint(0, n - 1)
            if j < self.RESERVOIR_SIZE:
                reservoir[j] = duration_ms

    @staticmethod
    def _compute_percentiles(samples: list[float]) -> dict:
        """Compute p50/p95/p99 from samples. Returns available values when sample count is low."""
        if not samples:
            return {"p50_ms": 0, "p95_ms": 0, "p99_ms": 0}
        s = sorted(samples)
        n = len(s)
        return {
            "p50_ms": round(s[n * 50 // 100], 1),
            "p95_ms": round(s[min(n * 95 // 100, n - 1)], 1),
            "p99_ms": round(s[min(n * 99 // 100, n - 1)], 1),
        }

    def summary(self) -> dict:
        per_tool = {}
        for tool, stats in self._per_tool.items():
            count = stats["count"]
            avg_ms = round(stats["total_ms"] / count, 1) if count > 0 else 0
            error_rate = round(stats["errors"] / count, 4) if count > 0 else 0
            percentiles = self._compute_percentiles(
                self._latency_reservoir.get(tool, [])
            )
            per_tool[tool] = {
                "count": count,
                "avg_ms": avg_ms,
                "errors": stats["errors"],
                "error_rate": error_rate,
                **percentiles,
            }

        return {
            "total_calls": self.total_calls,
            "total_errors": self.total_errors,
            "slow_queries": self.slow_queries,
            "per_tool": per_tool,
        }

    def trend(self) -> list[dict]:
        """Return summary snapshots from the most recent N periods (for trend comparison)."""
        return list(self._summary_history)

    def reset(self):
        """Reset current-period counters (trend history is preserved)."""
        self.total_calls = 0
        self.total_errors = 0
        self.slow_queries = 0
        self._per_tool.clear()
        self._latency_reservoir.clear()
        self._reservoir_n.clear()

    def log_summary(self):
        """Emit one summary audit record, save a snapshot to history, then reset counters."""
        if self.total_calls == 0:
            return

        snapshot = self.summary()
        snapshot["timestamp"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3]

        # Maintain the ring buffer
        self._summary_history.append(snapshot)
        if len(self._summary_history) > self.HISTORY_SIZE:
            self._summary_history = self._summary_history[-self.HISTORY_SIZE:]

        logger = get_audit_logger()
        if logger and logger.isEnabledFor(logging.INFO):
            logger.info(
                "",
                extra={
                    "event": "audit_summary",
                    "duration_ms": 0,
                    "status": "ok",
                    "slow": False,
                    "extra_fields": {
                        "pid": os.getpid(),
                        **snapshot,
                    },
                },
            )
        self.reset()

    async def periodic_summary(self):
        """Coroutine that emits periodic summaries (intended for asyncio.create_task)."""
        interval = config.AUDIT_SUMMARY_INTERVAL
        if interval <= 0:
            return
        try:
            while True:
                await asyncio.sleep(interval)
                self.log_summary()
        except asyncio.CancelledError:
            # Emit one final summary on shutdown
            self.log_summary()


# Global statistics instance
audit_stats = AuditStats()
