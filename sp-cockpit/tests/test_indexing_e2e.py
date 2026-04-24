"""E2E integration tests for the Indexing Admin feature.

Uses httpx TestClient against a real FastAPI app with a temp indexing.db.
Subprocess/docker calls inside backend integrators are mocked so no actual
docker compose or indexer containers are needed.

Flow covered:
  a. POST /api/indexing/jobs → creates job (201)
  b. GET /api/indexing/repos → lists repo with the running job
  c. POST same (repo, backend) while running → 409
  d. POST /api/indexing/jobs/{id}/finish → transitions to success
  e. GET /api/indexing/jobs/{id}/log → returns eof:true when finished
  f. DELETE /api/indexing/repos/{id}?backend=... → 200
  g. GET /api/indexing/repos → row gone (or archived)

NOTE: This test suite requires tasks #1-#5 to be complete (API + CLI + backends).
If the indexing API router is not yet registered, tests are skipped gracefully.
"""
from __future__ import annotations

import os
import pytest

# ---------------------------------------------------------------------------
# Optional skip — phases #4/#5 may not be landed yet
# ---------------------------------------------------------------------------
try:
    from sp_cockpit.api import indexing as _indexing_mod  # noqa: F401
    _INDEXING_API_AVAILABLE = True
except ImportError:
    _INDEXING_API_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _INDEXING_API_AVAILABLE,
    reason="sp_cockpit.api.indexing not yet available — phases #4/#5 pending",
)

# ---------------------------------------------------------------------------
# Imports (only reached when API is available)
# ---------------------------------------------------------------------------
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from sp_cockpit import config as av_config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Point SP_COCKPIT_INDEXING_DB_PATH at a fresh temp SQLite file."""
    db_path = tmp_path / "indexing_test.db"
    monkeypatch.setattr(av_config, "SP_COCKPIT_INDEXING_DB_PATH", db_path)
    monkeypatch.setenv("SP_COCKPIT_INDEXING_DB_PATH", str(db_path))
    # Also override internal token so auth checks pass
    monkeypatch.setattr(av_config, "INDEXING_INTERNAL_TOKEN", "test-token")
    monkeypatch.setenv("INDEXING_INTERNAL_TOKEN", "test-token")
    return db_path


@pytest.fixture()
def client(tmp_db):
    """TestClient for the full app with mocked backend integrators."""
    from sp_cockpit.api.app import create_app

    # Mock subprocess.Popen so 'trigger' backends don't actually launch docker
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None  # still running

    # Mock hard_delete to succeed silently
    with patch("subprocess.Popen", return_value=mock_proc), \
         patch("subprocess.run", return_value=MagicMock(returncode=0)):
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


INTERNAL_HEADERS = {"X-Indexing-Internal-Token": "test-token"}


# ---------------------------------------------------------------------------
# a) POST /api/indexing/jobs → 201
# ---------------------------------------------------------------------------

def test_create_job_returns_201(client):
    resp = client.post(
        "/api/indexing/jobs",
        json={"repo_path": "frameworks/base", "backend": "zoekt"},
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "job_id" in body
    assert body["status"] == "running"


# ---------------------------------------------------------------------------
# b) GET /api/indexing/repos lists repo
# ---------------------------------------------------------------------------

def test_list_repos_shows_created_job(client):
    # Create a job first
    client.post(
        "/api/indexing/jobs",
        json={"repo_path": "frameworks/base", "backend": "zoekt"},
        headers=INTERNAL_HEADERS,
    )
    resp = client.get("/api/indexing/repos")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert isinstance(items, list)
    assert len(items) >= 1
    repo_paths = [r["repo_path"] for r in items]
    assert "frameworks/base" in repo_paths


# ---------------------------------------------------------------------------
# c) POST same (repo, backend) while running → 409
# ---------------------------------------------------------------------------

def test_duplicate_job_returns_409(client):
    payload = {"repo_path": "frameworks/base", "backend": "structural"}
    r1 = client.post("/api/indexing/jobs", json=payload, headers=INTERNAL_HEADERS)
    assert r1.status_code == 201, r1.text
    r2 = client.post("/api/indexing/jobs", json=payload, headers=INTERNAL_HEADERS)
    assert r2.status_code == 409, r2.text
    body = r2.json()
    detail = body.get("detail", body)
    assert "existing_job_id" in detail or "error" in detail


# ---------------------------------------------------------------------------
# d) POST /api/indexing/jobs/{id}/finish → transitions to success
# ---------------------------------------------------------------------------

def test_finish_job_transitions_to_success(client):
    r = client.post(
        "/api/indexing/jobs",
        json={"repo_path": "frameworks/base", "backend": "dense"},
        headers=INTERNAL_HEADERS,
    )
    assert r.status_code == 201
    job_id = r.json()["job_id"]

    fin = client.post(
        f"/api/indexing/jobs/{job_id}/finish",
        json={"status": "success", "exit_code": 0, "entity_count_after": 123},
        headers=INTERNAL_HEADERS,
    )
    assert fin.status_code == 200, fin.text
    assert fin.json()["status"] == "success"


# ---------------------------------------------------------------------------
# e) GET /api/indexing/jobs/{id}/log → eof:true after finish
# ---------------------------------------------------------------------------

def test_log_eof_true_after_finish(client, tmp_path):
    # Create a real log file so the endpoint can read it
    log_file = tmp_path / "job.log"
    log_file.write_text("line1\nline2\n")

    r = client.post(
        "/api/indexing/jobs",
        json={
            "repo_path": "frameworks/base",
            "backend": "zoekt",
            "log_path": str(log_file),
        },
        headers=INTERNAL_HEADERS,
    )
    assert r.status_code == 201
    job_id = r.json()["job_id"]

    # Before finish: eof should be False (job still running)
    log_resp = client.get(f"/api/indexing/jobs/{job_id}/log", params={"offset": 0})
    assert log_resp.status_code == 200
    assert log_resp.json()["eof"] is False

    # Finish the job
    client.post(
        f"/api/indexing/jobs/{job_id}/finish",
        json={"status": "success", "exit_code": 0},
        headers=INTERNAL_HEADERS,
    )

    # After finish: eof should be True
    log_resp2 = client.get(f"/api/indexing/jobs/{job_id}/log", params={"offset": 0})
    assert log_resp2.status_code == 200
    data = log_resp2.json()
    assert data["eof"] is True
    assert "line1" in data["content"]


# ---------------------------------------------------------------------------
# f) DELETE /api/indexing/repos/{id}?backend=... → 200
# ---------------------------------------------------------------------------

def test_delete_repo_backend_returns_200(client):
    r = client.post(
        "/api/indexing/jobs",
        json={"repo_path": "frameworks/base", "backend": "zoekt"},
        headers=INTERNAL_HEADERS,
    )
    assert r.status_code == 201
    job_id = r.json()["job_id"]
    # Finish first so it's not "running" (DELETE on running should block or warn)
    client.post(
        f"/api/indexing/jobs/{job_id}/finish",
        json={"status": "success", "exit_code": 0},
        headers=INTERNAL_HEADERS,
    )

    # Get repo id from list
    repos = client.get("/api/indexing/repos").json()["items"]
    repo = next((r for r in repos if r["repo_path"] == "frameworks/base"), None)
    assert repo is not None
    repo_id = repo["repo_id"]

    del_resp = client.delete(f"/api/indexing/repos/{repo_id}", params={"backend": "zoekt"})
    assert del_resp.status_code == 200, del_resp.text


# ---------------------------------------------------------------------------
# g) GET /api/indexing/repos → deleted row gone (or archived)
# ---------------------------------------------------------------------------

def test_repo_gone_after_delete(client):
    r = client.post(
        "/api/indexing/jobs",
        json={"repo_path": "to_delete/repo", "backend": "structural"},
        headers=INTERNAL_HEADERS,
    )
    assert r.status_code == 201
    job_id = r.json()["job_id"]
    client.post(
        f"/api/indexing/jobs/{job_id}/finish",
        json={"status": "success", "exit_code": 0},
        headers=INTERNAL_HEADERS,
    )

    repos_before = client.get("/api/indexing/repos").json()["items"]
    repo = next((r for r in repos_before if r["repo_path"] == "to_delete/repo"), None)
    assert repo is not None
    repo_id = repo["repo_id"]

    client.delete(f"/api/indexing/repos/{repo_id}", params={"backend": "structural"})

    repos_after = client.get("/api/indexing/repos").json()["items"]
    remaining = [r for r in repos_after if r["repo_path"] == "to_delete/repo"]
    # After deletion the row should be gone or archived (not listed as active)
    active = [r for r in remaining if not r.get("archived_at")]
    assert len(active) == 0, f"Expected deleted repo to be gone, got: {active}"


# ---------------------------------------------------------------------------
# CORS: POST + DELETE must be in allowed methods (R1 from plan)
# ---------------------------------------------------------------------------

def test_cors_allows_post_and_delete(client):
    resp = client.options(
        "/api/indexing/jobs",
        headers={
            "Origin": "http://localhost:9100",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code in (200, 204)
    allow_methods = resp.headers.get("access-control-allow-methods", "")
    assert "POST" in allow_methods.upper() or allow_methods == "*"
