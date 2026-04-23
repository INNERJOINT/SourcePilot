"""Tests for sp_cockpit.indexing_db module."""
import pytest
import sqlite3
from pathlib import Path

from sp_cockpit import indexing_db


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test_indexing.db"
    c = indexing_db.open_and_bootstrap(db_path)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Bootstrap / schema
# ---------------------------------------------------------------------------

def test_bootstrap_creates_tables(conn):
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "index_repos" in tables
    assert "index_jobs" in tables
    assert "indexing_meta" in tables


def test_wal_mode(conn):
    row = conn.execute("PRAGMA journal_mode").fetchone()
    assert row[0] == "wal"


def test_schema_version_stamped(conn):
    version = indexing_db.get_meta(conn, "schema_version")
    assert version == "2"


# ---------------------------------------------------------------------------
# Repo helpers
# ---------------------------------------------------------------------------

def test_upsert_repo_insert(conn):
    repo_id = indexing_db.upsert_repo(conn, "/aosp/frameworks/base")
    assert isinstance(repo_id, int)
    assert repo_id > 0


def test_upsert_repo_idempotent(conn):
    id1 = indexing_db.upsert_repo(conn, "/aosp/frameworks/base")
    id2 = indexing_db.upsert_repo(conn, "/aosp/frameworks/base")
    assert id1 == id2


def test_get_repo(conn):
    indexing_db.upsert_repo(conn, "/aosp/art")
    row = indexing_db.get_repo(conn, "/aosp/art")
    assert row is not None
    assert row["repo_path"] == "/aosp/art"
    assert row["archived_at"] is None


def test_archive_repo(conn):
    repo_id = indexing_db.upsert_repo(conn, "/aosp/bionic")
    indexing_db.archive_repo(conn, repo_id, ts_ms=1_700_000_000_000)
    row = indexing_db.get_repo(conn, "/aosp/bionic")
    assert row["archived_at"] == 1_700_000_000_000


# ---------------------------------------------------------------------------
# Job helpers
# ---------------------------------------------------------------------------

def test_create_job(conn):
    repo_id = indexing_db.upsert_repo(conn, "/aosp/frameworks/base")
    job_id = indexing_db.create_job(conn, repo_id, "zoekt")
    assert job_id > 0
    row = indexing_db.get_job(conn, job_id)
    assert row["status"] == "pending"
    assert row["backend"] == "zoekt"


def test_start_job(conn):
    repo_id = indexing_db.upsert_repo(conn, "/aosp/frameworks/base")
    job_id = indexing_db.create_job(conn, repo_id, "dense")
    indexing_db.start_job(conn, job_id)
    row = indexing_db.get_job(conn, job_id)
    assert row["status"] == "running"


def test_finish_job_success(conn):
    repo_id = indexing_db.upsert_repo(conn, "/aosp/frameworks/base")
    job_id = indexing_db.create_job(conn, repo_id, "graph")
    indexing_db.start_job(conn, job_id)
    indexing_db.finish_job(conn, job_id, "success", exit_code=0, entity_count_after=42)
    row = indexing_db.get_job(conn, job_id)
    assert row["status"] == "success"
    assert row["exit_code"] == 0
    assert row["entity_count_after"] == 42
    assert row["finished_at"] is not None


def test_finish_job_fail(conn):
    repo_id = indexing_db.upsert_repo(conn, "/aosp/frameworks/base")
    job_id = indexing_db.create_job(conn, repo_id, "zoekt")
    indexing_db.start_job(conn, job_id)
    indexing_db.finish_job(conn, job_id, "fail", exit_code=1)
    row = indexing_db.get_job(conn, job_id)
    assert row["status"] == "fail"
    assert row["exit_code"] == 1


def test_backend_constraint(conn):
    repo_id = indexing_db.upsert_repo(conn, "/aosp/frameworks/base")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO index_jobs(repo_id, backend, status) VALUES(?, 'invalid_backend', 'pending')",
            (repo_id,),
        )
        conn.commit()


def test_status_constraint(conn):
    repo_id = indexing_db.upsert_repo(conn, "/aosp/frameworks/base")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO index_jobs(repo_id, backend, status) VALUES(?, 'zoekt', 'bad_status')",
            (repo_id,),
        )
        conn.commit()


def test_singleton_lock_blocks_second_running(conn):
    """Only one 'running' job per repo+backend allowed."""
    repo_id = indexing_db.upsert_repo(conn, "/aosp/frameworks/base")
    job1 = indexing_db.create_job(conn, repo_id, "zoekt")
    indexing_db.start_job(conn, job1)
    # second job in pending state — fine
    job2 = indexing_db.create_job(conn, repo_id, "zoekt")
    # attempting to start the second one should violate the unique partial index
    with pytest.raises(sqlite3.IntegrityError):
        indexing_db.start_job(conn, job2)


def test_get_running_job(conn):
    repo_id = indexing_db.upsert_repo(conn, "/aosp/frameworks/base")
    job_id = indexing_db.create_job(conn, repo_id, "dense")
    assert indexing_db.get_running_job(conn, repo_id, "dense") is None
    indexing_db.start_job(conn, job_id)
    running = indexing_db.get_running_job(conn, repo_id, "dense")
    assert running is not None
    assert running["id"] == job_id


def test_multiple_backends_independent(conn):
    """Different backends for same repo have independent singleton locks."""
    repo_id = indexing_db.upsert_repo(conn, "/aosp/frameworks/base")
    j_zoekt = indexing_db.create_job(conn, repo_id, "zoekt")
    j_dense = indexing_db.create_job(conn, repo_id, "dense")
    indexing_db.start_job(conn, j_zoekt)
    # dense should start fine — different backend
    indexing_db.start_job(conn, j_dense)
    assert indexing_db.get_running_job(conn, repo_id, "zoekt")["id"] == j_zoekt
    assert indexing_db.get_running_job(conn, repo_id, "dense")["id"] == j_dense
