"""
MCP 审计日志模块

提供结构化 JSON 审计日志，记录每次工具调用的详细信息（耗时、结果数、状态等），
支持性能调优和运营监控。

用法:
    from observability.audit import setup_audit_logger, audit_tool_call, audit_stats

    setup_audit_logger("stdio")  # 或 "http"

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


# ─── 请求级 trace_id ────────────────────────────────────
# TODO: extract trace_id management to observability/tracing.py when OTel/spans are added

_trace_id: ContextVar[str] = ContextVar("audit_trace_id", default="")


def new_trace_id() -> str:
    """生成新的 trace_id 并设置到当前上下文。返回 trace_id。"""
    tid = uuid.uuid4().hex
    _trace_id.set(tid)
    return tid


def get_trace_id() -> str:
    """获取当前上下文的 trace_id（无则返回空字符串）。"""
    return _trace_id.get()


# ─── JSON 格式化器 ────────────────────────────────────


def _truncate(obj, max_bytes: int = 1024) -> tuple:
    """JSON 序列化后超过 max_bytes 则截断，返回 (value, truncated_flag)。"""
    try:
        serialized = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        serialized = str(obj)
    if len(serialized.encode("utf-8")) <= max_bytes:
        return obj, False
    return serialized[:max_bytes] + "...", True


class JsonFormatter(logging.Formatter):
    """将 LogRecord 格式化为单行 JSON，按 event 类型使用不同 schema。"""

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event", "unknown")

        # 公共字段
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
            stage_result = getattr(record, "stage_result", {})
            stage_result, result_truncated = _truncate(stage_result)
            data["stage_result"] = stage_result
            if result_truncated:
                data["stage_result_truncated"] = True

        elif event == "audit_summary":
            extra_fields = getattr(record, "extra_fields", None)
            if extra_fields:
                data.update(extra_fields)

        error_message = getattr(record, "error_message", None)
        if error_message:
            data["error_message"] = error_message

        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


# ─── 非阻塞队列 Handler ─────────────────────────────────

class _NonBlockingQueueHandler(QueueHandler):
    """QueueHandler 子类：队列满时静默丢弃，不阻塞 event loop。"""

    def __init__(self, q: queue.Queue):
        super().__init__(q)
        self.dropped_count = 0

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            self.dropped_count += 1


# ─── 审计日志器设置 ───────────────────────────────────

_audit_logger: logging.Logger | None = None
_queue_listener: QueueListener | None = None
_queue_handler: _NonBlockingQueueHandler | None = None


def setup_audit_logger(transport_mode: str = "stdio") -> logging.Logger:
    """初始化审计专用 logger。

    Args:
        transport_mode: "stdio" 或 "http"。
            stdio: 默认写文件（RotatingFileHandler），避免污染 MCP JSON-RPC。
            http: 默认写 stderr（StreamHandler）。

    Returns:
        配置好的 audit logger。
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

    # 确定实际输出目标
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

    # 通过 QueueHandler + QueueListener 异步化写入
    q: queue.Queue = queue.Queue(maxsize=10000)
    _queue_handler = _NonBlockingQueueHandler(q)
    _queue_listener = QueueListener(q, real_handler, respect_handler_level=True)
    logger.addHandler(_queue_handler)

    _audit_logger = logger
    return logger


def start_audit_listener():
    """启动 QueueListener 后台线程（在 app lifespan 中调用）。"""
    if _queue_listener is not None:
        _queue_listener.start()


def stop_audit_listener():
    """停止 QueueListener 后台线程（在 app lifespan 中调用）。"""
    if _queue_listener is not None:
        _queue_listener.stop()


def get_audit_logger() -> logging.Logger | None:
    """获取已初始化的审计 logger（未初始化返回 None）。"""
    return _audit_logger


def reset_audit_logger():
    """重置审计 logger（仅用于测试）。"""
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


# ─── 审计上下文管理器 ─────────────────────────────────

class AuditContext:
    """工具调用/流水线阶段审计上下文，用于收集结果信息。"""

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


# 从格式化文本中提取结果数的正则
_RESULT_COUNT_RE = re.compile(r"找到 (\d+)")


def extract_result_count(tool_name: str, text: str) -> int | None:
    """从工具返回的文本中提取结果数量。

    - search_code/symbol/file/regex/list_repos: 正则匹配 "找到 N"
    - get_file_content/read_resource: 硬编码 1
    - 无法提取时返回 None
    """
    if tool_name in ("get_file_content", "read_resource"):
        return 1

    match = _RESULT_COUNT_RE.search(text)
    if match:
        return int(match.group(1))
    return None


@asynccontextmanager
async def audit_tool_call(tool_name: str, arguments: dict, interface: str):
    """审计工具调用的异步上下文管理器。

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

        # 更新统计
        audit_stats.record(tool_name, duration_ms, status == "error", slow)


@asynccontextmanager
async def audit_stage(stage: str, metadata: dict | None = None):
    """审计流水线阶段的异步上下文管理器。

    Args:
        stage: 阶段名称（如 "classify", "rewrite", "zoekt_search", "rrf_merge", "rerank"）
        metadata: 阶段输入参数/配置（会记录到日志）

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

        # 将 stage 级别指标纳入统计
        audit_stats.record(stage, duration_ms, status == "error", slow)


# ─── 审计统计 ─────────────────────────────────────────

class AuditStats:
    """轻量级审计统计聚合器，支持 per-tool 错误率、百分位延迟、趋势历史。"""

    RESERVOIR_SIZE = 1000
    HISTORY_SIZE = 12  # 周期快照数（默认 5min × 12 = 1h）

    def __init__(self):
        self.total_calls = 0
        self.total_errors = 0
        self.slow_queries = 0
        self._per_tool: dict[str, dict] = {}
        self._latency_reservoir: dict[str, list[float]] = {}
        self._reservoir_n: dict[str, int] = {}  # Algorithm R 的总计数
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
        """从样本计算 p50/p95/p99。样本不足时返回可用值。"""
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
        """返回最近 N 个周期的摘要快照（用于趋势对比）。"""
        return list(self._summary_history)

    def reset(self):
        """重置当前周期计数（不清除趋势历史）。"""
        self.total_calls = 0
        self.total_errors = 0
        self.slow_queries = 0
        self._per_tool.clear()
        self._latency_reservoir.clear()
        self._reservoir_n.clear()

    def log_summary(self):
        """输出一条摘要审计记录，保存快照到历史，然后重置计数。"""
        if self.total_calls == 0:
            return

        snapshot = self.summary()
        snapshot["timestamp"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3]

        # 维护环形缓冲区
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
        """周期性输出摘要的协程（供 asyncio.create_task 调用）。"""
        interval = config.AUDIT_SUMMARY_INTERVAL
        if interval <= 0:
            return
        try:
            while True:
                await asyncio.sleep(interval)
                self.log_summary()
        except asyncio.CancelledError:
            # 关闭时输出最后一次摘要
            self.log_summary()


# 全局统计实例
audit_stats = AuditStats()
