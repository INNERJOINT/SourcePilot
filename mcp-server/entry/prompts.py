"""AOSP Code Search MCP — prompt templates (FastMCP).

Prompts guide the LLM on how to use the available tools for common
AOSP investigation workflows.
"""

from __future__ import annotations


def register_prompts(mcp: object) -> None:
    """Register all @server.prompt() handlers on the given FastMCP instance."""
    from mcp.server.fastmcp import FastMCP

    server: FastMCP = mcp  # type: ignore[assignment]

    @server.prompt(
        description=(
            "Guide the LLM to find all call sites of a symbol in AOSP source code "
            "using search_symbol + search_regex."
        )
    )
    def find_callers(
        symbol: str,
        repo: str | None = None,
        project: str | None = None,
    ) -> str:
        """Find all callers of a symbol in AOSP.

        Uses search_symbol to locate the definition and search_regex to enumerate
        every call site.  Optionally scoped to a specific repo and/or project.
        """
        ctx = f" in repo {repo!r}" if repo else ""
        proj = f" (project={project!r})" if project else ""
        return (
            f"Find all call sites of symbol {symbol!r}{ctx}{proj} in AOSP source code.\n\n"
            "Steps:\n"
            f"1. Run search_symbol(symbol={symbol!r}) to locate the definition and "
            "confirm its full qualified name.\n"
            f'2. Run search_regex(pattern=r"{symbol}\\s*\\(") to enumerate call patterns.\n'
            "3. For each match, use get_file_content to read the surrounding context "
            "(start_line minus 5, end_line plus 5).\n"
            "4. Deduplicate by (repo, filepath, line_number) and report each unique "
            "call site with its full path and line number."
        )
