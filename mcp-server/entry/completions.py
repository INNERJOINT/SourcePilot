"""B2: Completion suggestions for repo, project, and lang arguments."""

from __future__ import annotations

import logging

from mcp.types import Completion

logger = logging.getLogger(__name__)

_STATIC_LANGS = ["java", "kotlin", "cpp", "c", "python", "go", "rust", "js", "ts"]


def register_completions(mcp: object) -> None:
    """Register the @server.completion() handler on the FastMCP instance."""
    from mcp.server.fastmcp import FastMCP

    server: FastMCP = mcp  # type: ignore[assignment]

    @server.completion()
    async def handle_completion(ref, argument, context):  # noqa: ANN001
        """Return completion candidates for repo, project, and lang tool arguments."""
        arg_name: str = argument.name
        partial: str = argument.value or ""

        if arg_name == "lang":
            candidates = [v for v in _STATIC_LANGS if v.startswith(partial)]
            return Completion(values=candidates[:100], total=len(candidates), has_more=False)

        if arg_name in ("repo", "project"):
            from entry.tools_state import SOURCEPILOT_URL

            endpoint = "/api/list_repos" if arg_name == "repo" else "/api/projects"
            try:
                # Borrow the resource-level http client (lifespan-owned, set before yield)
                from entry.resources import _resource_client

                if _resource_client is None:
                    logger.warning("handle_completion: http client not ready, returning empty")
                    return Completion(values=[], total=0, has_more=False)

                if arg_name == "repo":
                    resp = await _resource_client.post(
                        f"{SOURCEPILOT_URL}{endpoint}",
                        json={"query": partial, "top_k": 100},
                    )
                else:
                    resp = await _resource_client.get(f"{SOURCEPILOT_URL}{endpoint}")

                resp.raise_for_status()
                data = resp.json()

                if arg_name == "repo":
                    # data is a list of {"name": ..., "url": ...}
                    raw = data if isinstance(data, list) else data.get("repos", [])
                    names = [r.get("name", "") for r in raw if r.get("name", "")]
                else:
                    # data is a list or {"projects": [...]}
                    raw = data if isinstance(data, list) else data.get("projects", [])
                    names = [p.get("name", "") for p in raw if p.get("name", "")]

                candidates = [n for n in names if partial.lower() in n.lower()][:100]
                return Completion(values=candidates, total=len(candidates), has_more=False)

            except Exception as exc:
                logger.warning("handle_completion(%s) failed: %s", arg_name, exc)
                return Completion(values=[], total=0, has_more=False)

        return None
