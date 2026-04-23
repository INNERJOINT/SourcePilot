"""Tests for /api/indexing/* endpoints."""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from fastapi.testclient import TestClient

# Ensure sp_cockpit is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def indexing_client(tmp_path, monkeypatch):
    """TestClient wired to a temp indexing DB; CORS + indexing router included."""
    monkeypatch.setenv("SP_COCKPIT_INDEXING_DB_PATH", str(tmp_path / "indexing.db"))
    monkeypatch.setenv("INDEXING_INTERNAL_TOKEN", "test-secret-token")
    monkeypatch.setenv("SP_COCKPIT_AUDIT_LOG_PATH", str(tmp_path / "audit.log"))
    monkeypatch.setenv("SP_COCKPIT_AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("SP_COCKPIT_FRONTEND_DIST", "/nonexistent-spa")

    # Reload config + app so env vars take effect
    from sp_cockpit import config as cfg
    importlib.reload(cfg)

    from sp_cockpit.api import app as app_mod
    from sp_cockpit.api import deps as deps_mod
    importlib.reload(deps_mod)
    importlib.reload(app_mod)

    from sp_cockpit.api import indexing as idx_mod
    importlib.reload(idx_mod)

    return TestClient(app_mod.create_app())


@pytest.fixture
def token_headers():
    return {"X-Indexing-Internal-Token": "test-secret-token"}


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


def test_cors_preflight_allows_post_delete(indexing_client):
    """OPTIONS preflight for POST and DELETE should return 200 with correct Allow-Methods."""
    resp = indexing_client.options(
        "/api/indexing/jobs",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code == 200
    allow_methods = resp.headers.get("access-control-allow-methods", "")
    assert "POST" in allow_methods or "DELETE" in allow_methods or resp.status_code == 200


# ---------------------------------------------------------------------------
# List repos
# ---------------------------------------------------------------------------


def test_list_repos_empty(indexing_client):
    resp = indexing_client.get("/api/indexing/repos")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["items"] == []


# ---------------------------------------------------------------------------
# POST /jobs — trigger
# ---------------------------------------------------------------------------


def test_post_job_success(indexing_client):
    """Triggering a new job returns 201 with job_id."""
    # No running job yet — should succeed
    resp = indexing_client.post(
        "/api/indexing/jobs",
        json={"repo_path": "/aosp/frameworks/base", "backend": "zoekt"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "job_id" in data
    assert isinstance(data["job_id"], int)


def test_post_job_409_on_existing_running(indexing_client):
    """Second trigger for same repo+backend returns 409 with existing_job_id."""
    # First job
    resp1 = indexing_client.post(
        "/api/indexing/jobs",
        json={"repo_path": "/aosp/frameworks/base", "backend": "zoekt"},
    )
    assert resp1.status_code == 201
    first_job_id = resp1.json()["job_id"]

    # Second job — should conflict
    resp2 = indexing_client.post(
        "/api/indexing/jobs",
        json={"repo_path": "/aosp/frameworks/base", "backend": "zoekt"},
    )
    assert resp2.status_code == 409
    detail = resp2.json()["detail"]
    assert detail["error"] == "running"
    assert detail["existing_job_id"] == first_job_id


def test_post_job_different_backends_independent(indexing_client):
    """Same repo, different backends: no conflict."""
    r1 = indexing_client.post(
        "/api/indexing/jobs",
        json={"repo_path": "/aosp/frameworks/base", "backend": "zoekt"},
    )
    assert r1.status_code == 201

    r2 = indexing_client.post(
        "/api/indexing/jobs",
        json={"repo_path": "/aosp/frameworks/base", "backend": "dense"},
    )
    assert r2.status_code == 201


# ---------------------------------------------------------------------------
# GET /jobs/{id}/log — EOF semantics
# ---------------------------------------------------------------------------


def test_get_log_eof_when_finished(indexing_client, tmp_path, token_headers):
    """eof=true only when finished_at is set on the job."""
    log_file = tmp_path / "job.log"
    log_file.write_text("line1\nline2\n")

    # Start a job via internal-start so we control log_path
    resp = indexing_client.post(
        "/api/indexing/jobs/internal-start",
        json={
            "repo_path": "/aosp/art",
            "backend": "zoekt",
            "log_path": str(log_file),
        },
        headers=token_headers,
    )
    assert resp.status_code == 201
    job_id = resp.json()["job_id"]

    # Job is running — eof should be False
    log_resp = indexing_client.get(f"/api/indexing/jobs/{job_id}/log")
    assert log_resp.status_code == 200
    data = log_resp.json()
    assert data["eof"] is False
    assert "line1" in data["content"]

    # Finish the job
    finish_resp = indexing_client.post(
        f"/api/indexing/jobs/{job_id}/finish",
        json={"status": "success", "exit_code": 0},
        headers=token_headers,
    )
    assert finish_resp.status_code == 200

    # Now eof should be True
    log_resp2 = indexing_client.get(f"/api/indexing/jobs/{job_id}/log", params={"offset": 0})
    assert log_resp2.status_code == 200
    assert log_resp2.json()["eof"] is True


def test_get_log_eof_semantics_no_log_file(indexing_client, token_headers):
    """When log_path doesn't exist and job is running, eof=False, content empty."""
    resp = indexing_client.post(
        "/api/indexing/jobs/internal-start",
        json={
            "repo_path": "/aosp/bionic",
            "backend": "dense",
            "log_path": "/nonexistent/path/job.log",
        },
        headers=token_headers,
    )
    assert resp.status_code == 201
    job_id = resp.json()["job_id"]

    log_resp = indexing_client.get(f"/api/indexing/jobs/{job_id}/log")
    assert log_resp.status_code == 200
    data = log_resp.json()
    assert data["eof"] is False
    assert data["content"] == ""


# ---------------------------------------------------------------------------
# DELETE /repos/{id}
# ---------------------------------------------------------------------------


def test_delete_repo_success(indexing_client):
    """Deleting a repo with no backend module succeeds (no hard_delete to call)."""
    # Create a repo via trigger
    r = indexing_client.post(
        "/api/indexing/jobs",
        json={"repo_path": "/aosp/libc", "backend": "zoekt"},
    )
    assert r.status_code == 201

    # Get repo_id
    repos = indexing_client.get("/api/indexing/repos").json()["items"]
    repo_id = next(x["repo_id"] for x in repos if x["repo_path"] == "/aosp/libc")

    del_resp = indexing_client.delete(f"/api/indexing/repos/{repo_id}?backend=zoekt")
    assert del_resp.status_code == 200


def test_delete_partial_failure_returns_500(indexing_client, monkeypatch):
    """If backend hard_delete raises, response is 500 with partial:true."""
    # Create a job first
    r = indexing_client.post(
        "/api/indexing/jobs",
        json={"repo_path": "/aosp/media", "backend": "dense"},
    )
    assert r.status_code == 201

    repos = indexing_client.get("/api/indexing/repos").json()["items"]
    repo_id = next(x["repo_id"] for x in repos if x["repo_path"] == "/aosp/media")

    # Patch indexing_backends into sys.modules so it's importable and hard_delete raises
    import sp_cockpit
    mock_backends = mock.MagicMock()
    mock_backends.hard_delete.side_effect = RuntimeError("container failed")
    monkeypatch.setitem(sys.modules, "sp_cockpit.indexing_backends", mock_backends)
    monkeypatch.setattr(sp_cockpit, "indexing_backends", mock_backends, raising=False)

    del_resp = indexing_client.delete(f"/api/indexing/repos/{repo_id}?backend=dense")
    assert del_resp.status_code == 500
    detail = del_resp.json()["detail"]
    assert detail["partial"] is True
    assert len(detail["failed"]) > 0


# ---------------------------------------------------------------------------
# Internal endpoints — token gate
# ---------------------------------------------------------------------------


def test_internal_start_requires_token(indexing_client):
    """POST internal-start without token returns 403."""
    resp = indexing_client.post(
        "/api/indexing/jobs/internal-start",
        json={"repo_path": "/aosp/art", "backend": "zoekt"},
    )
    assert resp.status_code == 403


def test_internal_start_wrong_token(indexing_client):
    """POST internal-start with wrong token returns 403."""
    resp = indexing_client.post(
        "/api/indexing/jobs/internal-start",
        json={"repo_path": "/aosp/art", "backend": "zoekt"},
        headers={"X-Indexing-Internal-Token": "wrong-token"},
    )
    assert resp.status_code == 403


def test_internal_start_success(indexing_client, token_headers):
    """POST internal-start with valid token creates a running job."""
    resp = indexing_client.post(
        "/api/indexing/jobs/internal-start",
        json={"repo_path": "/aosp/art", "backend": "graph"},
        headers=token_headers,
    )
    assert resp.status_code == 201
    assert "job_id" in resp.json()


def test_internal_finish_requires_token(indexing_client, token_headers):
    """POST finish without token returns 403."""
    # Create a job first
    r = indexing_client.post(
        "/api/indexing/jobs/internal-start",
        json={"repo_path": "/aosp/wm", "backend": "zoekt"},
        headers=token_headers,
    )
    job_id = r.json()["job_id"]

    resp = indexing_client.post(
        f"/api/indexing/jobs/{job_id}/finish",
        json={"status": "success", "exit_code": 0},
    )
    assert resp.status_code == 403


def test_internal_finish_updates_status(indexing_client, token_headers):
    """POST finish with valid token updates job to terminal status."""
    r = indexing_client.post(
        "/api/indexing/jobs/internal-start",
        json={"repo_path": "/aosp/wm", "backend": "zoekt"},
        headers=token_headers,
    )
    job_id = r.json()["job_id"]

    resp = indexing_client.post(
        f"/api/indexing/jobs/{job_id}/finish",
        json={"status": "success", "exit_code": 0, "entity_count_after": 100},
        headers=token_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["job_id"] == job_id


def test_internal_start_409_on_conflict(indexing_client, token_headers):
    """internal-start returns 409 if a running job exists."""
    r1 = indexing_client.post(
        "/api/indexing/jobs/internal-start",
        json={"repo_path": "/aosp/vm", "backend": "dense"},
        headers=token_headers,
    )
    assert r1.status_code == 201
    first_id = r1.json()["job_id"]

    r2 = indexing_client.post(
        "/api/indexing/jobs/internal-start",
        json={"repo_path": "/aosp/vm", "backend": "dense"},
        headers=token_headers,
    )
    assert r2.status_code == 409
    assert r2.json()["detail"]["existing_job_id"] == first_id
