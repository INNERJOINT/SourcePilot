"""
审计日志模块测试

测试 audit.py 的核心功能：JSON 格式化、计时、错误处理、慢查询标记、
开关控制、propagate 隔离、统计聚合。
"""

import asyncio
import json
import logging
import os
import sys
import tempfile

import pytest

# 确保能 import 项目模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "aosp_search"))

# 设定环境变量（在 import 之前）
os.environ.setdefault("ZOEKT_URL", "http://mock-zoekt:6070")
os.environ.setdefault("NL_ENABLED", "false")


from aosp_search.audit import (
    AuditContext,
    AuditStats,
    JsonFormatter,
    audit_tool_call,
    audit_stage,
    extract_result_count,
    new_trace_id,
    get_trace_id,
    reset_audit_logger,
    setup_audit_logger,
)
from aosp_search import config


# ─── Fixtures ─────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_audit():
    """每个测试前后重置审计 logger 和配置。"""
    reset_audit_logger()
    # 保存原始值
    orig_enabled = config.AUDIT_ENABLED
    orig_slow_ms = config.AUDIT_SLOW_QUERY_MS
    orig_log_file = config.AUDIT_LOG_FILE
    yield
    # 恢复
    reset_audit_logger()
    config.AUDIT_ENABLED = orig_enabled
    config.AUDIT_SLOW_QUERY_MS = orig_slow_ms
    config.AUDIT_LOG_FILE = orig_log_file


class LogCapture(logging.Handler):
    """捕获日志记录用于断言。"""

    def __init__(self):
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord):
        self.records.append(self.format(record))


def _setup_with_capture() -> LogCapture:
    """设置审计 logger 并附加一个内存捕获 handler。"""
    config.AUDIT_ENABLED = True
    config.AUDIT_LOG_FILE = ""  # 不写文件
    logger = setup_audit_logger("http")  # http 模式 → stderr handler
    # 添加一个捕获 handler
    capture = LogCapture()
    capture.setFormatter(JsonFormatter())
    logger.addHandler(capture)
    return capture


# ─── 测试 ─────────────────────────────────────────────

class TestJsonFormat:
    """测试 1: JSON 格式合法性 + 必需字段。"""

    @pytest.mark.asyncio
    async def test_json_format(self):
        capture = _setup_with_capture()

        async with audit_tool_call("search_code", {"query": "test"}, "mcp") as ctx:
            ctx.set_result_count(5)

        assert len(capture.records) == 1
        data = json.loads(capture.records[0])

        # 必需字段检查
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
    """测试 2: duration_ms > 0。"""

    @pytest.mark.asyncio
    async def test_duration_recorded(self):
        capture = _setup_with_capture()

        async with audit_tool_call("search_symbol", {"symbol": "Foo"}, "mcp") as ctx:
            await asyncio.sleep(0.01)  # 确保有可测量的耗时
            ctx.set_result_count(1)

        data = json.loads(capture.records[0])
        assert data["duration_ms"] > 0


class TestErrorStatus:
    """测试 3: 异常时 status='error' + error_message。"""

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
    """测试 4: 超阈值时 slow=true。"""

    @pytest.mark.asyncio
    async def test_slow_query_flag(self):
        capture = _setup_with_capture()
        config.AUDIT_SLOW_QUERY_MS = 10  # 10ms 阈值

        async with audit_tool_call("search_regex", {"pattern": ".*"}, "mcp") as ctx:
            await asyncio.sleep(0.02)  # 20ms > 10ms 阈值
            ctx.set_result_count(3)

        data = json.loads(capture.records[0])
        assert data["slow"] is True
        assert data["duration_ms"] > 10


class TestAuditDisabled:
    """测试 5: AUDIT_ENABLED=false 时无审计输出。"""

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
    """测试 6: audit logger 不向 root logger 传播。"""

    @pytest.mark.asyncio
    async def test_propagate_false(self):
        _setup_with_capture()

        # 在 root logger 上添加捕获
        root_capture = LogCapture()
        root_capture.setFormatter(logging.Formatter("%(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(root_capture)

        try:
            async with audit_tool_call("list_repos", {"query": ""}, "mcp") as ctx:
                ctx.set_result_count(10)

            # root logger 不应收到任何 audit 记录
            audit_in_root = [r for r in root_capture.records if "tool_call" in r]
            assert len(audit_in_root) == 0
        finally:
            root_logger.removeHandler(root_capture)


class TestStatsSummary:
    """测试 7: AuditStats 正确累计。"""

    def test_stats_aggregation(self):
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
        stats = AuditStats()
        stats.record("search_code", 100.0, False, False)
        stats.reset()

        summary = stats.summary()
        assert summary["total_calls"] == 0
        assert summary["per_tool"] == {}


class TestExtractResultCount:
    """测试 extract_result_count 辅助函数。"""

    def test_search_results(self):
        text = '找到 10 条与 "test" 相关的代码：\n'
        assert extract_result_count("search_code", text) == 10

    def test_list_repos(self):
        text = "找到 5 个仓库：\n"
        assert extract_result_count("list_repos", text) == 5

    def test_get_file_content(self):
        text = "# repo/file (L1-L100 / 共 100 行)"
        assert extract_result_count("get_file_content", text) == 1

    def test_read_resource(self):
        text = "# repo/file (共 200 行)"
        assert extract_result_count("read_resource", text) == 1

    def test_no_match(self):
        assert extract_result_count("search_code", "未找到相关代码。") is None


class TestAuditLogFile:
    """测试审计日志写入文件。"""

    @pytest.mark.asyncio
    async def test_file_handler(self):
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            log_path = f.name

        try:
            config.AUDIT_ENABLED = True
            config.AUDIT_LOG_FILE = log_path
            setup_audit_logger("stdio")

            async with audit_tool_call("search_code", {"query": "file_test"}, "mcp") as ctx:
                ctx.set_result_count(3)

            # 读取文件验证
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            assert len(lines) >= 1
            data = json.loads(lines[0])
            assert data["tool"] == "search_code"
            assert data["result_count"] == 3
        finally:
            os.unlink(log_path)


class TestTraceId:
    """测试 trace_id 生成与传播。"""

    def test_new_trace_id_format(self):
        """trace_id 是 32 字符的 hex 字符串。"""
        tid = new_trace_id()
        assert len(tid) == 32
        assert all(c in "0123456789abcdef" for c in tid)

    def test_get_trace_id_returns_current(self):
        """get_trace_id 返回最近 new_trace_id 设置的值。"""
        tid = new_trace_id()
        assert get_trace_id() == tid

    @pytest.mark.asyncio
    async def test_trace_id_in_tool_call_log(self):
        """audit_tool_call 记录包含当前 trace_id。"""
        capture = _setup_with_capture()
        tid = new_trace_id()

        async with audit_tool_call("search_code", {"query": "test"}, "mcp") as ctx:
            ctx.set_result_count(1)

        data = json.loads(capture.records[0])
        assert data["trace_id"] == tid


class TestAuditStage:
    """测试 audit_stage 上下文管理器。"""

    @pytest.mark.asyncio
    async def test_stage_basic(self):
        """audit_stage 记录包含 stage、metadata、result。"""
        capture = _setup_with_capture()
        new_trace_id()

        async with audit_stage("classify", {"query": "test"}) as stg:
            stg.set_result({"query_type": "exact"})

        data = json.loads(capture.records[0])
        assert data["event"] == "pipeline_stage"
        assert data["stage"] == "classify"
        assert data["result"]["query_type"] == "exact"
        assert data["metadata"]["query"] == "test"
        assert data["duration_ms"] >= 0
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_stage_error(self):
        """audit_stage 异常时记录 error。"""
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
        """同一请求内的多个 stage 共享同一 trace_id。"""
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
        """AUDIT_ENABLED=false 时 audit_stage 无输出。"""
        config.AUDIT_ENABLED = False
        reset_audit_logger()
        logger = setup_audit_logger("http")
        capture = LogCapture()
        capture.setFormatter(JsonFormatter())
        logger.addHandler(capture)

        async with audit_stage("classify", {"query": "test"}) as stg:
            stg.set_result({"query_type": "exact"})

        assert len(capture.records) == 0
