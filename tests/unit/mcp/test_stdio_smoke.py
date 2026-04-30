"""Tests: stdio mode is unaffected by MCP_AUTH_TOKEN check."""

import sys


def test_stdio_import_no_system_exit(monkeypatch):
    """Importing entry.mcp_stdio with empty MCP_AUTH_TOKEN raises no SystemExit."""
    monkeypatch.setenv("MCP_AUTH_TOKEN", "")

    sys.modules.pop("entry.mcp_stdio", None)

    try:
        import entry.mcp_stdio  # noqa: F401
    except SystemExit as exc:
        raise AssertionError(
            "entry.mcp_stdio raised SystemExit on import with empty token"
        ) from exc
    except Exception:
        # Import-time errors unrelated to token check are acceptable
        pass
