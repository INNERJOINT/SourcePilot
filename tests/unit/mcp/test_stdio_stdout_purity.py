"""
Stdout purity test for MCP stdio transport.

Spawns `python -u -m mcp_server -t stdio` and verifies that every
non-empty line written to stdout is valid JSON containing a `jsonrpc`
field.  Log output must go to stderr only.
"""

import json
import os
import subprocess
import sys
import time

import pytest

_MCP_SERVER_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp-server")
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".")

_INITIALIZE_MSG = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
) + "\n"

_INITIALIZED_NOTIF = json.dumps(
    {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }
) + "\n"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only subprocess test")
def test_stdio_stdout_is_pure_jsonrpc():
    """Every non-empty stdout line from stdio mode must be valid JSON with jsonrpc field."""
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": os.path.abspath(_MCP_SERVER_DIR)}

    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "mcp_server", "-t", "stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=os.path.abspath(_REPO_ROOT),
        env=env,
    )

    stdout_lines: list[str] = []
    try:
        # Send initialize
        assert proc.stdin is not None
        proc.stdin.write(_INITIALIZE_MSG.encode())
        proc.stdin.flush()

        # Read stdout for up to 5 seconds, collecting lines
        deadline = time.monotonic() + 5.0
        assert proc.stdout is not None
        proc.stdout.fileno()  # ensure it's a real fd

        import select

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            ready, _, _ = select.select([proc.stdout], [], [], max(0.0, remaining))
            if not ready:
                break
            line = proc.stdout.readline()
            if not line:
                break
            decoded = line.decode(errors="replace").rstrip("\n")
            if decoded.strip():
                stdout_lines.append(decoded)
            # Once we have at least one response, send initialized and break
            if stdout_lines:
                proc.stdin.write(_INITIALIZED_NOTIF.encode())
                proc.stdin.flush()
                # Read a bit more
                time.sleep(0.2)
                break

        # Drain any remaining buffered lines (non-blocking)
        import fcntl

        fl = fcntl.fcntl(proc.stdout.fileno(), fcntl.F_GETFL)
        fcntl.fcntl(proc.stdout.fileno(), fcntl.F_SETFL, fl | os.O_NONBLOCK)
        try:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                decoded = line.decode(errors="replace").rstrip("\n")
                if decoded.strip():
                    stdout_lines.append(decoded)
        except (BlockingIOError, OSError):
            pass

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    assert stdout_lines, "Expected at least one JSON-RPC response on stdout"

    for line in stdout_lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            pytest.fail(f"Non-JSON line on stdout: {line!r}  ({exc})")
        assert "jsonrpc" in obj, (
            f"stdout line is JSON but missing 'jsonrpc' field: {line!r}"
        )
