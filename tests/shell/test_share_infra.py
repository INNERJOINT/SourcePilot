"""Tests for scripts/share/_infra.sh helpers."""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


class _OKHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass  # suppress


@pytest.fixture()
def http_server():
    """Spin up a tiny HTTP server on a random port, yield (host, port), then tear down."""
    srv = HTTPServer(("127.0.0.1", 0), _OKHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield "127.0.0.1", port
    srv.shutdown()


@pytest.fixture()
def free_port():
    """Return a port that is NOT listening."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _infra_preamble(proj_root: Path) -> str:
    return f"""
        export INFRA_SLEEP_SECONDS=0
        export SOURCEPILOT_ENV_NO_AUTOLOAD=1
        source "{proj_root}/scripts/share/_common.sh"
        source "{proj_root}/scripts/share/_env.sh"
        source "{proj_root}/scripts/share/_infra.sh"
    """


def test_infra_wait_http_success(run_bash, proj_root, http_server):
    """_infra_wait_http succeeds against a live server."""
    host, port = http_server
    r = run_bash(
        _infra_preamble(proj_root)
        + f"""
        _infra_wait_http "http://{host}:{port}/" "test-svc" 3 die
        echo "RESULT=$?"
        """,
        env={"SOURCEPILOT_ENV_NO_AUTOLOAD": "1", "INFRA_SLEEP_SECONDS": "0"},
    )
    assert r.returncode == 0
    assert "RESULT=0" in r.stdout


def test_infra_wait_http_timeout(run_bash, proj_root, free_port):
    """_infra_wait_http with 'warn' returns 1 on timeout."""
    r = run_bash(
        _infra_preamble(proj_root)
        + f"""
        _infra_wait_http "http://127.0.0.1:{free_port}/" "test-svc" 2 warn || true
        echo "DONE"
        """,
        env={"SOURCEPILOT_ENV_NO_AUTOLOAD": "1", "INFRA_SLEEP_SECONDS": "0"},
    )
    assert r.returncode == 0
    assert "DONE" in r.stdout


def test_infra_wait_http_die(run_bash, proj_root, free_port):
    """_infra_wait_http with 'die' exits non-zero on timeout."""
    r = run_bash(
        _infra_preamble(proj_root)
        + f"""
        _infra_wait_http "http://127.0.0.1:{free_port}/" "test-svc" 2 die
        """,
        env={"SOURCEPILOT_ENV_NO_AUTOLOAD": "1", "INFRA_SLEEP_SECONDS": "0"},
    )
    assert r.returncode != 0


def test_infra_wait_tcp_success(run_bash, proj_root, http_server):
    """_infra_wait_tcp succeeds against a live port."""
    host, port = http_server
    r = run_bash(
        _infra_preamble(proj_root)
        + f"""
        _infra_wait_tcp "{host}" {port} "test-tcp" 3
        echo "RESULT=$?"
        """,
        env={"SOURCEPILOT_ENV_NO_AUTOLOAD": "1", "INFRA_SLEEP_SECONDS": "0"},
    )
    assert r.returncode == 0
    assert "RESULT=0" in r.stdout


def test_infra_wait_tcp_timeout(run_bash, proj_root, free_port):
    """_infra_wait_tcp returns 1 on timeout."""
    r = run_bash(
        _infra_preamble(proj_root)
        + f"""
        _infra_wait_tcp "127.0.0.1" {free_port} "test-tcp" 2 || true
        echo "DONE"
        """,
        env={"SOURCEPILOT_ENV_NO_AUTOLOAD": "1", "INFRA_SLEEP_SECONDS": "0"},
    )
    assert r.returncode == 0
    assert "DONE" in r.stdout


def test_infra_require_cmd_exists(run_bash, proj_root):
    """_infra_require_cmd passes for an existing command."""
    r = run_bash(
        _infra_preamble(proj_root)
        + """
        _infra_require_cmd bash
        echo "OK"
        """,
        env={"SOURCEPILOT_ENV_NO_AUTOLOAD": "1", "INFRA_SLEEP_SECONDS": "0"},
    )
    assert r.returncode == 0
    assert "OK" in r.stdout


def test_infra_require_cmd_missing(run_bash, proj_root):
    """_infra_require_cmd dies for a missing command."""
    r = run_bash(
        _infra_preamble(proj_root)
        + """
        _infra_require_cmd __no_such_cmd_xyz__ "install it"
        echo "SHOULD_NOT_REACH"
        """,
        env={"SOURCEPILOT_ENV_NO_AUTOLOAD": "1", "INFRA_SLEEP_SECONDS": "0"},
    )
    assert r.returncode != 0
    assert "SHOULD_NOT_REACH" not in r.stdout
    assert "__no_such_cmd_xyz__" in r.stderr


def test_infra_sleep_seconds_zero(run_bash, proj_root, free_port):
    """INFRA_SLEEP_SECONDS=0 makes retries instant (fast test)."""
    r = run_bash(
        _infra_preamble(proj_root)
        + f"""
        _infra_wait_http "http://127.0.0.1:{free_port}/" "fast" 3 warn || true
        echo "DONE"
        """,
        env={"SOURCEPILOT_ENV_NO_AUTOLOAD": "1", "INFRA_SLEEP_SECONDS": "0"},
        timeout=5,
    )
    assert "DONE" in r.stdout


def test_source_guard(run_bash, proj_root):
    """Sourcing _infra.sh twice is idempotent."""
    r = run_bash(
        f"""
        export SOURCEPILOT_ENV_NO_AUTOLOAD=1
        export INFRA_SLEEP_SECONDS=0
        source "{proj_root}/scripts/share/_common.sh"
        source "{proj_root}/scripts/share/_env.sh"
        source "{proj_root}/scripts/share/_infra.sh"
        source "{proj_root}/scripts/share/_infra.sh"
        echo "OK"
        """,
        env={"SOURCEPILOT_ENV_NO_AUTOLOAD": "1", "INFRA_SLEEP_SECONDS": "0"},
    )
    assert r.returncode == 0
    assert "OK" in r.stdout
