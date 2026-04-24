import os
import stat
import subprocess
from pathlib import Path


def test_build_index_preserves_caller_env_vars(tmp_path: Path) -> None:
    """Caller-provided env vars must override values loaded from .env files."""

    # Create isolated tree matching script's expected layout.
    proj_root = tmp_path
    deploy_dense_scripts = proj_root / "deploy" / "dense" / "scripts"
    deploy_dense_scripts.mkdir(parents=True)
    (proj_root / "deploy" / "docker-compose.yml").write_text("services: {}\n")

    repo_script = (
        Path(__file__).resolve().parents[2] / "deploy" / "dense" / "scripts" / "build_index.sh"
    )
    script_copy = deploy_dense_scripts / "build_index.sh"
    script_copy.write_text(repo_script.read_text())
    script_copy.chmod(script_copy.stat().st_mode | stat.S_IXUSR)

    # Conflicting values in .env files should NOT override caller env.
    (proj_root / ".env").write_text(
        "AOSP_SOURCE_ROOT=/from_root_env\n"
        "DENSE_COLLECTION_NAME=collection_from_root_env\n"
        "DENSE_VECTOR_DB_URL=http://root-env:19530\n"
    )
    (proj_root / "deploy" / "dense" / ".env").write_text(
        "AOSP_SOURCE_ROOT=/from_dense_env\n"
        "DENSE_COLLECTION_NAME=collection_from_dense_env\n"
        "DENSE_VECTOR_DB_URL=http://dense-env:19530\n"
    )

    # Fake docker prints received env and args, then exits successfully.
    fake_bin = proj_root / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'echo "DOCKER_ENV:AOSP_SOURCE_ROOT=${AOSP_SOURCE_ROOT:-}"\n'
        'echo "DOCKER_ENV:DENSE_COLLECTION_NAME=${DENSE_COLLECTION_NAME:-}"\n'
        'echo "DOCKER_ENV:DENSE_VECTOR_DB_URL=${DENSE_VECTOR_DB_URL:-}"\n'
        'for arg in "$@"; do echo "DOCKER_ARG:$arg"; done\n'
    )
    fake_docker.chmod(fake_docker.stat().st_mode | stat.S_IXUSR)

    caller_root = proj_root / "caller_root"
    source_dir = caller_root / "frameworks" / "base"
    source_dir.mkdir(parents=True)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["AOSP_SOURCE_ROOT"] = str(caller_root)
    env["DENSE_COLLECTION_NAME"] = "collection_from_caller"
    env["DENSE_VECTOR_DB_URL"] = "http://caller-env:19530"

    proc = subprocess.run(
        [
            "bash",
            str(script_copy),
            "--source-dir",
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
    assert "DOCKER_ENV:DENSE_COLLECTION_NAME=collection_from_caller" in out
    assert "DOCKER_ENV:DENSE_VECTOR_DB_URL=http://caller-env:19530" in out
    assert "DOCKER_ARG:--source-dir" in out
    assert "DOCKER_ARG:/src/frameworks/base" in out
