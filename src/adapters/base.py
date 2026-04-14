"""SearchAdapter ABC and unified data structures."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ContentType(Enum):
    CODE = "code"
    DOCUMENT = "document"
    MESSAGE = "message"
    ISSUE = "issue"
    CONFIG = "config"


@dataclass
class QueryOptions:
    max_results: int = 10
    timeout_ms: int = 30000
    cursor: str | None = None


@dataclass
class Highlight:
    text: str
    ranges: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class SearchItem:
    id: str
    source: str
    content_type: ContentType
    title: str
    summary: str
    url: str
    score: float
    timestamp: str | None = None
    matched_terms: list[str] = field(default_factory=list)
    highlights: list[Highlight] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BackendQuery:
    raw_query: str
    parsed: dict  # ParsedQuery later
    backend_specific: dict = field(default_factory=dict)
    options: QueryOptions = field(default_factory=QueryOptions)


@dataclass
class BackendResponse:
    backend: str
    status: str  # "ok" | "error" | "timeout" | "partial"
    latency_ms: float
    total_hits: int
    items: list[SearchItem] = field(default_factory=list)
    error_detail: str | None = None
    cursor: str | None = None


class SearchAdapter(ABC):
    """检索后端统一适配器接口"""

    @abstractmethod
    async def search(self, query: BackendQuery) -> BackendResponse:
        """执行检索，返回统一格式结果"""
        ...

    @abstractmethod
    async def get_content(self, item_id: str) -> dict:
        """获取单条内容的完整内容"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """后端健康检查"""
        ...

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """后端标识名"""
        ...

    @property
    @abstractmethod
    def supported_content_types(self) -> list[ContentType]:
        """该后端支持的内容类型"""
        ...
