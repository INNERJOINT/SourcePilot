import importlib.util
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "indexing" / "build_graph_index.py"
_SPEC = importlib.util.spec_from_file_location("build_graph_index_for_tests", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
bgi = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bgi)


def test_derive_repo_and_path_with_explicit_repo_name():
    repo, rel_path, mode = bgi._derive_repo_and_path(
        file_path="/mnt/code/ACE/frameworks/base/core/java/Foo.java",
        source_root="/mnt/code/ACE",
        project="ace",
        repo_name="frameworks/base",
    )

    assert repo == "frameworks/base"
    assert rel_path == "frameworks/base/core/java/Foo.java"
    assert mode == "explicit"


def test_derive_repo_and_path_frameworks_default():
    repo, rel_path, mode = bgi._derive_repo_and_path(
        file_path="/mnt/code/ACE/frameworks/base/core/java/Foo.java",
        source_root="/mnt/code/ACE",
        project="ace",
    )

    assert repo == "frameworks/base"
    assert rel_path == "core/java/Foo.java"
    assert mode == "derived"


def test_derive_repo_and_path_packages_default():
    repo, rel_path, mode = bgi._derive_repo_and_path(
        file_path="/mnt/code/ACE/packages/modules/StatsD/src/Main.java",
        source_root="/mnt/code/ACE",
        project="ace",
    )

    assert repo == "packages/modules/StatsD"
    assert rel_path == "src/Main.java"
    assert mode == "derived"


def test_derive_repo_and_path_from_repo_root_source_root():
    repo, rel_path, mode = bgi._derive_repo_and_path(
        file_path="/mnt/code/ACE/frameworks/base/services/Service.java",
        source_root="/mnt/code/ACE/frameworks/base",
        project="ace",
    )

    assert repo == "frameworks/base"
    assert rel_path == "services/Service.java"
    assert mode == "derived"


def test_derive_repo_and_path_project_root_fallback():
    repo, rel_path, mode = bgi._derive_repo_and_path(
        file_path="/mnt/code/ACE/system/core/init/main.cpp",
        source_root="/mnt/code/ACE",
        project="ace",
    )

    assert repo == "ace"
    assert rel_path == "system/core/init/main.cpp"
    assert mode == "project_root"


def test_derive_repo_and_path_rejects_outside_source_root():
    with pytest.raises(ValueError, match="文件不在 source_root 下"):
        bgi._derive_repo_and_path(
            file_path="/mnt/code/OTHER/frameworks/base/Foo.java",
            source_root="/mnt/code/ACE",
            project="ace",
        )


class _FakeResult:
    def __init__(self, *, single_payload=None, data_payload=None):
        self._single_payload = single_payload or {}
        self._data_payload = data_payload or []

    def single(self):
        return self._single_payload

    def data(self):
        return self._data_payload


class _FakeSession:
    def __init__(self, *, missing_count=0, dup_rows=None, constraints_rows=None):
        self.missing_count = missing_count
        self.dup_rows = dup_rows or []
        self.constraints_rows = constraints_rows or []
        self.queries = []

    def run(self, query, **params):
        self.queries.append((query, params))
        if "RETURN count(f) AS cnt" in query:
            return _FakeResult(single_payload={"cnt": self.missing_count})
        if "RETURN project, repo, path, c" in query:
            return _FakeResult(data_payload=self.dup_rows)
        if "SHOW CONSTRAINTS" in query:
            return _FakeResult(data_payload=self.constraints_rows)
        return _FakeResult()


def test_preflight_fails_when_identity_fields_missing():
    session = _FakeSession(missing_count=1)

    with pytest.raises(RuntimeError, match="缺少 project/repo/path"):
        bgi._preflight_file_identity_constraints(session)

    assert not any("CREATE CONSTRAINT file_project_repo_path" in q for q, _ in session.queries)


def test_preflight_fails_when_composite_duplicates_exist():
    session = _FakeSession(
        missing_count=0,
        dup_rows=[{"project": "ace", "repo": "frameworks/base", "path": "A.java", "c": 2}],
    )

    with pytest.raises(RuntimeError, match="复合键重复"):
        bgi._preflight_file_identity_constraints(session)

    assert not any("CREATE CONSTRAINT file_project_repo_path" in q for q, _ in session.queries)


def test_preflight_creates_composite_and_drops_legacy_path_constraint():
    session = _FakeSession(
        missing_count=0,
        dup_rows=[],
        constraints_rows=[
            {"name": "file_path", "properties": ["path"]},
            {"name": "file_project_repo_path", "properties": ["project", "repo", "path"]},
            {"name": "legacy_file_path_unique", "properties": ["path"]},
        ],
    )

    bgi._preflight_file_identity_constraints(session)

    assert any("CREATE CONSTRAINT file_project_repo_path" in q for q, _ in session.queries)
    assert any("DROP CONSTRAINT file_path IF EXISTS" in q for q, _ in session.queries)
    assert any("DROP CONSTRAINT legacy_file_path_unique IF EXISTS" in q for q, _ in session.queries)


def test_graph_wrapper_preserves_caller_env_vars(tmp_path: Path) -> None:
    """Caller-provided env vars must override values loaded from .env files."""

    repo_root = Path(__file__).resolve().parents[2]

    # Create isolated project tree mirroring the script's expected layout:
    #   <tmp>/scripts/indexing/build_graph_index.sh
    #   <tmp>/scripts/indexing/_indexing_lib.sh
    #   <tmp>/scripts/share/_common.sh
    #   <tmp>/scripts/share/_env.sh
    #   <tmp>/deploy/docker-compose.yml
    #   <tmp>/deploy/graph/
    proj_root = tmp_path

    scripts_indexing = proj_root / "scripts" / "indexing"
    scripts_indexing.mkdir(parents=True)
    scripts_share = proj_root / "scripts" / "share"
    scripts_share.mkdir(parents=True)

    deploy_graph = proj_root / "deploy" / "graph"
    deploy_graph.mkdir(parents=True)
    (proj_root / "deploy" / "docker-compose.yml").write_text("services: {}\n")

    for src, dst in [
        (repo_root / "scripts" / "indexing" / "build_graph_index.sh", scripts_indexing / "build_graph_index.sh"),
        (repo_root / "scripts" / "indexing" / "_indexing_lib.sh", scripts_indexing / "_indexing_lib.sh"),
        (repo_root / "scripts" / "share" / "_common.sh", scripts_share / "_common.sh"),
        (repo_root / "scripts" / "share" / "_env.sh", scripts_share / "_env.sh"),
    ]:
        dst.write_text(src.read_text())
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR)

    # Conflicting values in .env files — must NOT win over caller env.
    (proj_root / ".env").write_text(
        "AOSP_SOURCE_ROOT=/from_root_env\n"
        "GRAPH_NEO4J_URI=bolt://root-env:7687\n"
    )
    (deploy_graph / ".env").write_text(
        "AOSP_SOURCE_ROOT=/from_graph_env\n"
        "GRAPH_NEO4J_URI=bolt://graph-env:7687\n"
    )

    # Fake docker that prints received env vars and passed args then exits 0.
    fake_bin = proj_root / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'echo "DOCKER_ENV:AOSP_SOURCE_ROOT=${AOSP_SOURCE_ROOT:-}"\n'
        'echo "DOCKER_ENV:GRAPH_NEO4J_URI=${GRAPH_NEO4J_URI:-}"\n'
        'for arg in "$@"; do echo "DOCKER_ARG:$arg"; done\n'
    )
    fake_docker.chmod(fake_docker.stat().st_mode | stat.S_IXUSR)

    caller_root = proj_root / "caller_root"
    source_dir = caller_root / "frameworks" / "base"
    source_dir.mkdir(parents=True)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["AOSP_SOURCE_ROOT"] = str(caller_root)
    env["GRAPH_NEO4J_URI"] = "bolt://caller:7687"

    proc = subprocess.run(
        [
            "bash",
            str(scripts_indexing / "build_graph_index.sh"),
            "--source-root",
            str(source_dir),
            "--repo-name",
            "frameworks/base",
        ],
        env=env,
        cwd=proj_root,
        check=True,
        text=True,
        capture_output=True,
    )

    out = proc.stdout
    assert f"DOCKER_ENV:AOSP_SOURCE_ROOT={caller_root}" in out
    assert "DOCKER_ENV:GRAPH_NEO4J_URI=bolt://caller:7687" in out
    assert "DOCKER_ARG:--source-root" in out
    assert "DOCKER_ARG:/src/frameworks/base" in out
