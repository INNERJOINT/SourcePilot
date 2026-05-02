"""Resource template: aosp://{repo}/{filepath}"""

from __future__ import annotations

import logging
import uuid

import httpx

from entry.tools_state import SOURCEPILOT_URL

logger = logging.getLogger(__name__)

# Module-level client set by lifespan (resources don't receive Context)
_resource_client: httpx.AsyncClient | None = None


def set_resource_client(client: httpx.AsyncClient) -> None:
    global _resource_client
    _resource_client = client


def register_resources(mcp: object) -> None:
    """Register AOSP resource template on the FastMCP instance."""
    from mcp.server.fastmcp import FastMCP

    server: FastMCP = mcp  # type: ignore[assignment]

    @server.resource(
        "aosp://{repo}/{filepath}",
        name="aosp-file",
        title="AOSP source file",
        description=(
            "Read the full content of a file from an AOSP repository. "
            "First use the search_file tool to find the correct repo and filepath."
        ),
        mime_type="text/plain",
    )
    async def read_aosp_file(repo: str, filepath: str) -> str:
        client = _resource_client
        if client is None:
            raise RuntimeError("HTTP client not initialised (lifespan not running)")

        trace_id = str(uuid.uuid4())
        try:
            resp = await client.post(
                f"{SOURCEPILOT_URL}/api/get_file_content",
                json={"repo": repo, "filepath": filepath},
                headers={"X-Trace-Id": trace_id},
            )
            resp.raise_for_status()
            result = resp.json()
        except httpx.TimeoutException as exc:
            raise ValueError(f"SourcePilot unreachable at {SOURCEPILOT_URL}") from exc
        except httpx.ConnectError as exc:
            raise ValueError(f"SourcePilot unreachable at {SOURCEPILOT_URL}") from exc
        except httpx.HTTPStatusError as exc:
            raise ValueError(f"SourcePilot error: {exc.response.status_code}") from exc

        total_lines = result.get("total_lines", 0)
        file_content = result.get("content", "")
        return f"# {repo}/{filepath}  ({total_lines} lines total)\n\n{file_content}"
