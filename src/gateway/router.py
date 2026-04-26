"""Query routing and parallel dispatch to search backends."""
import asyncio
import logging
import time
from adapters.base import SearchAdapter, BackendQuery, BackendResponse, QueryOptions

logger = logging.getLogger(__name__)


async def dispatch(
    adapters: list[SearchAdapter],
    raw_query: str,
    parsed: dict,
    backend_specific: dict | None = None,
    max_results: int = 10,
    timeout_ms: int = 30000,
) -> list[BackendResponse]:
    """Dispatch query to multiple adapters in parallel, with timeout handling."""
    query = BackendQuery(
        raw_query=raw_query,
        parsed=parsed,
        backend_specific=backend_specific or {},
        options=QueryOptions(max_results=max_results, timeout_ms=timeout_ms),
    )
    tasks = [_call_adapter(adapter, query) for adapter in adapters]
    return await asyncio.gather(*tasks)


async def _call_adapter(adapter: SearchAdapter, query: BackendQuery) -> BackendResponse:
    """Call a single adapter with timeout and error handling."""
    start = time.perf_counter()
    try:
        response = await asyncio.wait_for(
            adapter.search(query),
            timeout=query.options.timeout_ms / 1000.0,
        )
        return response
    except asyncio.TimeoutError:
        return BackendResponse(
            backend=adapter.backend_name,
            status="timeout",
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
            total_hits=0, items=[], error_detail="adapter timeout",
        )
    except Exception as e:
        return BackendResponse(
            backend=adapter.backend_name,
            status="error",
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
            total_hits=0, items=[], error_detail=str(e),
        )
