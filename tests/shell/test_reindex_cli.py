"""CLI behavior tests for scripts/indexing/sparse/reindex.sh.

Covers:
  - --help exits 0 with usage text
  - Unknown args exit non-zero with error message
  - --project without value exits non-zero
  - zoekt-git-index is invoked with -shard_prefix_override <project>_<sub_slug>
  - --all mode iterates all declared projects
  - failed sub-repo indexing is reported as FAILED
  - missing project.list causes non-zero exit
"""

from __future__ import annotations

import os

from tests.shell.conftest import PROJ_ROOT, _run_bash

REINDEX_SH = str(PROJ_ROOT / "scripts" / "indexing" / "sparse" / "reindex.sh")


def test_help_exits_zero():
    """--help prints usage and exits 0."""
    r = _run_bash(f'bash "{REINDEX_SH}" --help')
    assert r.returncode == 0
    assert "Usage" in r.stdout or "usage" in r.stdout.lower()


def test_unknown_arg_exits_nonzero():
    """Unknown arguments cause a non-zero exit with error message."""
    r = _run_bash(f'bash "{REINDEX_SH}" --bogus-flag 2>&1')
    assert r.returncode != 0
    assert "Unknown option" in r.stderr or "Unknown option" in r.stdout


def test_project_without_value_exits_nonzero():
    """--project without a following name exits non-zero."""
    r = _run_bash(f'bash "{REINDEX_SH}" --project 2>&1')
    assert r.returncode != 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_projects_config(tmp_path, projects):
    """Write a minimal projects.yaml and return its path.

    projects: list of dicts with keys: name, repo_path, index_dir
    """

    lines = ["projects:\n"]
    for p in projects:
        lines.append(f"  - name: {p['name']}\n")
        lines.append(f"    repo_path: {p['repo_path']}\n")
        lines.append(f"    index_dir: {p['index_dir']}\n")
        lines.append("    zoekt_url: http://localhost:6070\n")
    cfg = tmp_path / "projects.yaml"
    cfg.write_text("".join(lines))
    return cfg


def _make_repo(tmp_path, repo_name, sub_paths):
    """Create a fake repo dir with project.list and .git markers.

    Returns the repo_path (contains project.list).
    """
    repo_path = tmp_path / repo_name
    repo_path.mkdir(parents=True)
    source_root = repo_path.parent

    (repo_path / "project.list").write_text("\n".join(sub_paths) + "\n")

    for sp in sub_paths:
        git_dir = source_root / sp
        git_dir.mkdir(parents=True, exist_ok=True)
        (git_dir / ".git").write_text("gitdir: fake\n")

    return repo_path


def _base_env(tmp_path, mock_command_log):
    """Minimal env dict for running reindex.sh in tests."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "TERM": "dumb",
        "NO_COLOR": "1",
        "MOCK_COMMAND_LOG": str(mock_command_log),
        # Disable dry-run; we want real invocations (mocked via PATH)
        "INDEXING_DRY_RUN": "0",
        # Keep parallelism=1 so order is deterministic
    }


# ---------------------------------------------------------------------------
# T2 + T6: happy-path end-to-end
# ---------------------------------------------------------------------------


def test_reindex_project_invokes_zoekt_with_shard_prefix(tmp_path, mock_command):
    """zoekt-git-index is called with -shard_prefix_override <proj>_<sub_slug>."""
    add_command, read_calls = mock_command

    # Inject mocked zoekt-git-index into PATH
    mock_log = tmp_path / "mock-calls.jsonl"
    add_command("zoekt-git-index")

    # Build fake repo layout
    sub_paths = ["frameworks/base", "external/openssl"]
    repo_path = _make_repo(tmp_path, "aosp_repo", sub_paths)
    index_dir = tmp_path / "index"
    index_dir.mkdir()

    cfg = _make_fake_projects_config(
        tmp_path,
        [{"name": "testproj", "repo_path": str(repo_path), "index_dir": str(index_dir)}],
    )

    env = _base_env(tmp_path, mock_log)
    env["PROJECTS_CONFIG_PATH"] = str(cfg)
    # PATH already has fake-bin prepended by monkeypatch; pass it through
    env["PATH"] = os.environ["PATH"]  # monkeypatch already mutated os.environ

    r = _run_bash(f'bash "{REINDEX_SH}" --project testproj --parallelism 1', env=env)

    assert r.returncode == 0, f"stderr: {r.stderr}\nstdout: {r.stdout}"

    calls = read_calls()
    zoekt_calls = [c for c in calls if c["cmd"] == "zoekt-git-index"]
    assert len(zoekt_calls) == len(sub_paths), f"Expected {len(sub_paths)} calls, got {zoekt_calls}"

    prefixes_seen = set()
    for call in zoekt_calls:
        argv = call["argv"]
        assert "-shard_prefix_override" in argv, f"-shard_prefix_override missing in {argv}"
        idx = argv.index("-shard_prefix_override")
        prefixes_seen.add(argv[idx + 1])

    for sp in sub_paths:
        slug = sp.replace("/", "_")
        expected = f"testproj_{slug}"
        assert expected in prefixes_seen, (
            f"Expected prefix '{expected}' not found in {prefixes_seen}"
        )


def test_reindex_all_iterates_projects(tmp_path, mock_command):
    """--all mode (no --project flag) processes every declared project."""
    add_command, read_calls = mock_command

    mock_log = tmp_path / "mock-calls.jsonl"
    add_command("zoekt-git-index")

    # Two projects, each with one sub-path
    proj_a_repo = _make_repo(tmp_path, "repo_a", ["frameworks/base"])
    proj_b_repo = _make_repo(tmp_path, "repo_b", ["external/openssl"])
    index_dir_a = tmp_path / "idx_a"
    index_dir_b = tmp_path / "idx_b"
    index_dir_a.mkdir()
    index_dir_b.mkdir()

    cfg = _make_fake_projects_config(
        tmp_path,
        [
            {"name": "alpha", "repo_path": str(proj_a_repo), "index_dir": str(index_dir_a)},
            {"name": "beta", "repo_path": str(proj_b_repo), "index_dir": str(index_dir_b)},
        ],
    )

    env = _base_env(tmp_path, mock_log)
    env["PROJECTS_CONFIG_PATH"] = str(cfg)
    env["PATH"] = os.environ["PATH"]

    r = _run_bash(f'bash "{REINDEX_SH}" --all --parallelism 1', env=env)

    assert r.returncode == 0, f"stderr: {r.stderr}\nstdout: {r.stdout}"

    combined = r.stdout + r.stderr
    assert "alpha" in combined, "Project 'alpha' not mentioned in output"
    assert "beta" in combined, "Project 'beta' not mentioned in output"

    calls = read_calls()
    zoekt_calls = [c for c in calls if c["cmd"] == "zoekt-git-index"]
    # One sub-path per project → 2 invocations total
    assert len(zoekt_calls) == 2, f"Expected 2 zoekt calls, got {zoekt_calls}"

    prefixes = {c["argv"][c["argv"].index("-shard_prefix_override") + 1] for c in zoekt_calls}
    assert any(p.startswith("alpha_") for p in prefixes), f"No alpha_ prefix in {prefixes}"
    assert any(p.startswith("beta_") for p in prefixes), f"No beta_ prefix in {prefixes}"


# ---------------------------------------------------------------------------
# T3: failure paths
# ---------------------------------------------------------------------------


def test_reindex_project_reports_failed_sub(tmp_path, mock_command):
    """When zoekt-git-index exits non-zero the script reports FAILED."""
    add_command, read_calls = mock_command

    mock_log = tmp_path / "mock-calls.jsonl"
    add_command("zoekt-git-index", exit_code=1)

    repo_path = _make_repo(tmp_path, "aosp_repo", ["frameworks/base"])
    index_dir = tmp_path / "index"
    index_dir.mkdir()

    cfg = _make_fake_projects_config(
        tmp_path,
        [{"name": "failproj", "repo_path": str(repo_path), "index_dir": str(index_dir)}],
    )

    env = _base_env(tmp_path, mock_log)
    env["PROJECTS_CONFIG_PATH"] = str(cfg)
    env["PATH"] = os.environ["PATH"]

    r = _run_bash(f'bash "{REINDEX_SH}" --project failproj --parallelism 1', env=env)

    # Script completes (it handles failure internally via status_dir/fail_count)
    combined = r.stdout + r.stderr
    assert "FAILED" in combined, f"Expected 'FAILED' in output:\n{combined}"


def test_reindex_missing_project_list_exits_nonzero(tmp_path, mock_command):
    """project.list not found causes non-zero exit."""
    add_command, _ = mock_command

    # No project.list created — just the repo dir
    repo_path = tmp_path / "empty_repo"
    repo_path.mkdir()
    index_dir = tmp_path / "index"
    index_dir.mkdir()

    cfg = _make_fake_projects_config(
        tmp_path,
        [{"name": "noproj", "repo_path": str(repo_path), "index_dir": str(index_dir)}],
    )

    env = _base_env(tmp_path, tmp_path / "mock-calls.jsonl")
    env["PROJECTS_CONFIG_PATH"] = str(cfg)
    env["PATH"] = os.environ["PATH"]

    r = _run_bash(f'bash "{REINDEX_SH}" --project noproj', env=env)

    assert r.returncode != 0, f"Expected non-zero exit; stdout: {r.stdout}\nstderr: {r.stderr}"
