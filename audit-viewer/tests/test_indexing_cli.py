"""Tests for audit_viewer.indexing_cli module."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(command="start", **kwargs):
    """Build a fake argparse.Namespace for the given subcommand."""
    import argparse
    defaults = {
        "command": command,
        "api_url": "http://localhost:9100",
    }
    if command == "start":
        defaults.update({"repo_path": "/aosp/frameworks/base", "backend": "dense", "log_path": None})
    elif command == "finish":
        defaults.update({"job_id": "42", "status": "success", "exit_code": 0})
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# test_start_sends_correct_payload
# ---------------------------------------------------------------------------

def test_start_sends_correct_payload():
    """start subcommand POSTs correct JSON payload."""
    from audit_viewer import indexing_cli

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = {"job_id": 7}

    with patch.object(indexing_cli, "_post_with_retry", return_value=(mock_resp, None)) as mock_post:
        args = _make_args("start", repo_path="/aosp/art", backend="graph", log_path="/tmp/art.log")
        rc = indexing_cli.cmd_start(args)

    assert rc == 0
    mock_post.assert_called_once()
    url, payload = mock_post.call_args[0]
    assert "/api/indexing/jobs/internal-start" in url
    assert payload["repo_path"] == "/aosp/art"
    assert payload["backend"] == "graph"
    assert payload["log_path"] == "/tmp/art.log"


def test_start_omits_log_path_when_none():
    """log_path key absent when not provided."""
    from audit_viewer import indexing_cli

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = {"job_id": 1}

    with patch.object(indexing_cli, "_post_with_retry", return_value=(mock_resp, None)) as mock_post:
        args = _make_args("start", log_path=None)
        indexing_cli.cmd_start(args)

    _, payload = mock_post.call_args[0]
    assert "log_path" not in payload


def test_start_409_prints_existing_id(capsys):
    """start subcommand prints existing JOB_ID on 409 and exits 2."""
    from audit_viewer import indexing_cli

    mock_resp = MagicMock()
    mock_resp.status_code = 409
    mock_resp.is_success = False
    mock_resp.json.return_value = {"job_id": 99}

    with patch.object(indexing_cli, "_post_with_retry", return_value=(mock_resp, None)):
        args = _make_args("start")
        rc = indexing_cli.cmd_start(args)

    assert rc == 2
    captured = capsys.readouterr()
    assert "JOB_ID=99" in captured.out


# ---------------------------------------------------------------------------
# test_start_retries_on_timeout
# ---------------------------------------------------------------------------

def test_start_retries_on_timeout():
    """_post_with_retry retries up to `retries` times on exception."""
    import httpx
    from audit_viewer import indexing_cli

    call_count = 0

    def fake_post(url, json, headers, timeout):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.TimeoutException("timeout")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.is_success = True
        mock_resp.json.return_value = {"job_id": 5}
        return mock_resp

    with patch("httpx.post", side_effect=fake_post):
        with patch("time.sleep"):  # avoid actual sleep
            resp, exc = indexing_cli._post_with_retry("http://x/y", {}, retries=3)

    assert exc is None
    assert call_count == 3


def test_start_returns_exc_after_all_retries_fail():
    """_post_with_retry returns (None, exc) when all retries exhausted."""
    import httpx
    from audit_viewer import indexing_cli

    with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
        with patch("time.sleep"):
            resp, exc = indexing_cli._post_with_retry("http://x/y", {}, retries=3)

    assert resp is None
    assert exc is not None


# ---------------------------------------------------------------------------
# test_finish_fallback_on_network_error
# ---------------------------------------------------------------------------

def test_finish_fallback_on_network_error(tmp_path, monkeypatch):
    """finish writes fallback JSON when network fails."""
    from audit_viewer import indexing_cli

    monkeypatch.chdir(tmp_path)

    with patch.object(indexing_cli, "_post_with_retry", return_value=(None, ConnectionError("down"))):
        args = _make_args("finish", job_id="17", status="fail", exit_code=1)
        rc = indexing_cli.cmd_finish(args)

    assert rc == 0  # non-fatal
    fallback_file = tmp_path / ".omc" / "indexing-fallback" / "17.json"
    assert fallback_file.exists(), f"Expected fallback at {fallback_file}"
    data = json.loads(fallback_file.read_text())
    assert data["job_id"] == "17"
    assert data["status"] == "fail"
    assert data["exit_code"] == 1
    assert "fallback_ts" in data


def test_finish_no_fallback_on_success(tmp_path, monkeypatch):
    """finish does NOT write fallback when API responds 200."""
    from audit_viewer import indexing_cli

    monkeypatch.chdir(tmp_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True

    with patch.object(indexing_cli, "_post_with_retry", return_value=(mock_resp, None)):
        args = _make_args("finish", job_id="5", status="success", exit_code=0)
        rc = indexing_cli.cmd_finish(args)

    assert rc == 0
    fallback_dir = tmp_path / ".omc" / "indexing-fallback"
    assert not fallback_dir.exists() or not list(fallback_dir.glob("*.json"))


# ---------------------------------------------------------------------------
# test_cli_integration_via_subprocess (requires running API or mock server)
# ---------------------------------------------------------------------------

def test_cli_start_via_subprocess_network_error(tmp_path, monkeypatch):
    """Running CLI as subprocess returns non-zero on connection refused."""
    monkeypatch.chdir(tmp_path)
    result = subprocess.run(
        [
            sys.executable, "-m", "audit_viewer.indexing_cli",
            "start",
            "--repo-path", "/aosp/frameworks/base",
            "--backend", "dense",
            "--api-url", "http://127.0.0.1:19999",  # nothing listening
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={**__import__("os").environ, "INDEXING_INTERNAL_TOKEN": "test-token", "PYTHONPATH": str(__import__("pathlib").Path(__file__).parent.parent)},
    )
    # Should fail (network error) with non-zero exit
    assert result.returncode != 0


def test_cli_finish_fallback_via_subprocess(tmp_path):
    """Running CLI finish as subprocess creates fallback on connection refused."""
    result = subprocess.run(
        [
            sys.executable, "-m", "audit_viewer.indexing_cli",
            "--api-url", "http://127.0.0.1:19999",  # nothing listening
            "finish",
            "--job-id", "999",
            "--status", "fail",
            "--exit-code", "1",
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={**__import__("os").environ, "INDEXING_INTERNAL_TOKEN": "test-token", "PYTHONPATH": str(__import__("pathlib").Path(__file__).parent.parent)},
    )
    # finish is non-fatal — should exit 0 and write fallback
    assert result.returncode == 0
    fallback = tmp_path / ".omc" / "indexing-fallback" / "999.json"
    assert fallback.exists()
    data = json.loads(fallback.read_text())
    assert data["job_id"] == "999"
