"""
Verify that importing entry.handlers installs a root logger StreamHandler
whose stream is sys.stderr (defense-in-depth: MCP stdio mode must never
pollute stdout with log output).
"""

import importlib
import logging
import sys

import pytest


@pytest.fixture(autouse=True)
def _reset_root_handlers():
    """Remove handlers added during the test so we don't leak state."""
    root = logging.getLogger()
    before = list(root.handlers)
    yield
    # Restore exactly the handlers that existed before the test.
    root.handlers = before


def test_handlers_module_installs_stderr_stream_handler():
    """entry.handlers calls basicConfig(stream=sys.stderr) at import time.

    logging.basicConfig is a no-op when handlers already exist, so we
    temporarily clear all root handlers before reloading the module, then
    verify that the reload installs exactly the expected StreamHandler.
    """
    import entry.handlers as handlers_mod  # noqa: PLC0415

    root = logging.getLogger()
    saved = list(root.handlers)
    # Clear so basicConfig actually fires.
    root.handlers.clear()
    try:
        importlib.reload(handlers_mod)
        stderr_handlers = [
            h
            for h in root.handlers
            if isinstance(h, logging.StreamHandler) and h.stream is sys.stderr
        ]
        assert stderr_handlers, (
            "Expected at least one root StreamHandler with stream=sys.stderr after "
            "reloading entry.handlers with empty root handlers, but found none.  "
            f"root.handlers = {root.handlers!r}"
        )
    finally:
        # Restore original handlers regardless of test outcome.
        root.handlers = saved
