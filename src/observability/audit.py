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
import re
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

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

class JsonFormatter(logging.Formatter):
    """将 LogRecord 格式化为单行 JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
            "trace_id": getattr(record, "trace_id", "") or get_trace_id(),
            "event": getattr(record, "event", "unknown"),
            "interface": getattr(record, "interface", ""),
            "tool": getattr(record, "tool", ""),
            "arguments": getattr(record, "arguments", {}),
            "duration_ms": getattr(record, "duration_ms", 0),
            "result_count": getattr(record, "result_count", None),
            "status": getattr(record, "status", "ok"),
            "slow": getattr(record, "slow", False),
        }

        # pipeline_stage 事件的额外字段
        stage = getattr(record, "stage", None)
        if stage:
            data["stage"] = stage
            data["metadata"] = getattr(record, "metadata", {})
            data["result"] = getattr(record, "result", {})

        error_message = getattr(record, "error_message", None)
        if error_message:
            data["error_message"] = error_message

        # 周期性摘要的额外字段
        extra_fields = getattr(record, "extra_fields", None)
        if extra_fields:
            data.update(extra_fields)

        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


# ─── 审计日志器设置 ───────────────────────────────────

_audit_logger: logging.Logger | None = None


def setup_audit_logger(transport_mode: str = "stdio") -> logging.Logger:
    """初始化审计专用 logger。

    Args:
        transport_mode: "stdio" 或 "http"。
            stdio: 默认写文件（RotatingFileHandler），避免污染 MCP JSON-RPC。
            http: 默认写 stderr（StreamHandler）。

    Returns:
        配置好的 audit logger。
    """
    global _audit_logger
    if _audit_logger is not None:
        return _audit_logger

    if not config.AUDIT_ENABLED:
        # 禁用时返回一个不输出任何内容的 logger
        logger = logging.getLogger("audit")
        logger.propagate = False
        logger.addHandler(logging.NullHandler())
        logger.setLevel(logging.CRITICAL + 1)
        _audit_logger = logger
        return logger

    logger = logging.getLogger("audit")
    logger.propagate = False  # 关键：防止 root logger 重复输出
    logger.setLevel(logging.INFO)

    formatter = JsonFormatter()

    # 确定输出目标
    log_file = config.AUDIT_LOG_FILE
    if not log_file and transport_mode == "stdio":
        log_file = "audit.log"

    if log_file:
        handler = RotatingFileHandler(
            log_file,
            maxBytes=50 * 1024 * 1024,  # 50 MB
            backupCount=5,
            encoding="utf-8",
        )
    else:
        # HTTP 模式默认写 stderr
        import sys
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    _audit_logger = logger
    return logger


def get_audit_logger() -> logging.Logger | None:
    """获取已初始化的审计 logger（未初始化返回 None）。"""
    return _audit_logger


def reset_audit_logger():
    """重置审计 logger（仅用于测试）。"""
    global _audit_logger
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

        logger = get_audit_logger()
        if logger and logger.isEnabledFor(logging.INFO):
            logger.info(
                "",
                extra={
                    "event": "pipeline_stage",
                    "trace_id": get_trace_id(),
                    "stage": stage,
                    "metadata": metadata or {},
                    "result": ctx.result or {},
                    "interface": "",
                    "tool": "",
                    "arguments": {},
                    "duration_ms": duration_ms,
                    "result_count": ctx.result_count,
                    "status": status,
                    "error_message": ctx.error_message,
                    "slow": duration_ms > config.AUDIT_SLOW_QUERY_MS,
                },
            )


# ─── 审计统计 ─────────────────────────────────────────

class AuditStats:
    """轻量级审计统计聚合器。"""

    def __init__(self):
        self.total_calls = 0
        self.total_errors = 0
        self.slow_queries = 0
        self._per_tool: dict[str, dict] = {}

    def record(self, tool: str, duration_ms: float, is_error: bool, is_slow: bool):
        if not config.AUDIT_ENABLED:
            return
        self.total_calls += 1
        if is_error:
            self.total_errors += 1
        if is_slow:
            self.slow_queries += 1

        if tool not in self._per_tool:
            self._per_tool[tool] = {"count": 0, "total_ms": 0.0}
        self._per_tool[tool]["count"] += 1
        self._per_tool[tool]["total_ms"] += duration_ms

    def summary(self) -> dict:
        per_tool = {}
        for tool, stats in self._per_tool.items():
            count = stats["count"]
            avg_ms = round(stats["total_ms"] / count, 1) if count > 0 else 0
            per_tool[tool] = {"count": count, "avg_ms": avg_ms}

        return {
            "total_calls": self.total_calls,
            "total_errors": self.total_errors,
            "slow_queries": self.slow_queries,
            "per_tool": per_tool,
        }

    def reset(self):
        self.total_calls = 0
        self.total_errors = 0
        self.slow_queries = 0
        self._per_tool.clear()

    def log_summary(self):
        """输出一条摘要审计记录并重置计数。"""
        if self.total_calls == 0:
            return

        logger = get_audit_logger()
        if logger and logger.isEnabledFor(logging.INFO):
            logger.info(
                "",
                extra={
                    "event": "audit_summary",
                    "interface": "all",
                    "tool": "",
                    "arguments": {},
                    "duration_ms": 0,
                    "result_count": None,
                    "status": "ok",
                    "slow": False,
                    "extra_fields": {
                        "pid": os.getpid(),
                        **self.summary(),
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
