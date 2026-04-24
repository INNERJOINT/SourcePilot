"""Unit tests for scripts/indexing/project_config.py"""

import json
import os
import textwrap

import project_config as pc
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_yaml(tmp_path, content: str):
    p = tmp_path / "projects.yaml"
    p.write_text(textwrap.dedent(content))
    return str(p)


# ---------------------------------------------------------------------------
# Backward-compatible load_projects behavior
# ---------------------------------------------------------------------------


def test_yaml_minimal(tmp_path):
    cfg = write_yaml(
        tmp_path,
        """
        projects:
          - name: ace
            source_root: /mnt/code/ACE
    """,
    )
    projects = pc.load_projects(cfg)
    assert len(projects) == 1
    p = projects[0]
    assert p["name"] == "ace"
    assert p["source_root"] == "/mnt/code/ACE"
    assert p["collection_name"] == "aosp_code_ace"
    assert p["sub_project_globs"] == []


def test_yaml_collection_name_override(tmp_path):
    cfg = write_yaml(
        tmp_path,
        """
        projects:
          - name: aosp15
            source_root: /mnt/code/AOSP15
            collection_name: my_custom_collection
    """,
    )
    projects = pc.load_projects(cfg)
    assert projects[0]["collection_name"] == "my_custom_collection"


def test_yaml_sub_project_globs(tmp_path):
    cfg = write_yaml(
        tmp_path,
        """
        projects:
          - name: ace
            source_root: /mnt/code/ACE
            sub_project_globs:
              - frameworks/*
              - system/core/*
    """,
    )
    projects = pc.load_projects(cfg)
    assert projects[0]["sub_project_globs"] == ["frameworks/*", "system/core/*"]


def test_yaml_two_projects(tmp_path):
    cfg = write_yaml(
        tmp_path,
        """
        projects:
          - name: ace
            source_root: /mnt/code/ACE
          - name: aosp15
            source_root: /mnt/code/AOSP15
    """,
    )
    projects = pc.load_projects(cfg)
    assert len(projects) == 2
    assert {p["name"] for p in projects} == {"ace", "aosp15"}


# ---------------------------------------------------------------------------
# Config path precedence
# ---------------------------------------------------------------------------


def test_precedence_env_over_default(monkeypatch, tmp_path):
    default_dir = tmp_path / "repo"
    (default_dir / "config").mkdir(parents=True)
    (default_dir / "config" / "projects.yaml").write_text(
        textwrap.dedent(
            """
            projects:
              - name: default_proj
                source_root: /mnt/code/default
            """
        )
    )

    env_cfg = write_yaml(
        tmp_path,
        """
        projects:
          - name: env_proj
            source_root: /mnt/code/env
        """,
    )

    monkeypatch.setattr(pc, "_PROJ_ROOT", default_dir)
    monkeypatch.setenv("PROJECTS_CONFIG_PATH", env_cfg)

    payload = pc.build_backend_config("dense")
    assert [p["name"] for p in payload["projects"]] == ["env_proj"]
    assert payload["config_path"] == os.path.realpath(env_cfg)


def test_precedence_explicit_over_env(monkeypatch, tmp_path):
    env_cfg = write_yaml(
        tmp_path,
        """
        projects:
          - name: env_proj
            source_root: /mnt/code/env
        """,
    )
    explicit_cfg = write_yaml(
        tmp_path,
        """
        projects:
          - name: explicit_proj
            source_root: /mnt/code/explicit
        """,
    )

    monkeypatch.setenv("PROJECTS_CONFIG_PATH", env_cfg)

    payload = pc.build_backend_config("dense", config_path=explicit_cfg)
    assert [p["name"] for p in payload["projects"]] == ["explicit_proj"]
    assert payload["config_path"] == os.path.realpath(explicit_cfg)


def test_fallback_uses_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AOSP_SOURCE_ROOT", "/mnt/code/MY_PROJECT")
    monkeypatch.delenv("PROJECTS_CONFIG_PATH", raising=False)
    monkeypatch.setattr(pc, "_PROJ_ROOT", tmp_path)
    projects = pc.load_projects()
    assert len(projects) == 1
    assert projects[0]["source_root"] == "/mnt/code/MY_PROJECT"
    assert projects[0]["name"] == "my_project"
    assert projects[0]["collection_name"] == "aosp_code_my_project"


def test_fallback_default_source_root(monkeypatch, tmp_path):
    monkeypatch.delenv("AOSP_SOURCE_ROOT", raising=False)
    monkeypatch.delenv("PROJECTS_CONFIG_PATH", raising=False)
    monkeypatch.setattr(pc, "_PROJ_ROOT", tmp_path)
    projects = pc.load_projects()
    assert projects[0]["source_root"] == "/mnt/code/ACE"


# ---------------------------------------------------------------------------
# Name/path validation
# ---------------------------------------------------------------------------


def test_invalid_name_uppercase(tmp_path):
    cfg = write_yaml(
        tmp_path,
        """
        projects:
          - name: ACE
            source_root: /mnt/code/ACE
    """,
    )
    with pytest.raises(ValueError, match="Invalid project name"):
        pc.load_projects(cfg)


def test_invalid_name_spaces(tmp_path):
    cfg = write_yaml(
        tmp_path,
        """
        projects:
          - name: "foo bar"
            source_root: /mnt/code/ACE
    """,
    )
    with pytest.raises(ValueError, match="Invalid project name"):
        pc.load_projects(cfg)


def test_invalid_name_hyphen(tmp_path):
    cfg = write_yaml(
        tmp_path,
        """
        projects:
          - name: foo-bar
            source_root: /mnt/code/ACE
    """,
    )
    with pytest.raises(ValueError, match="Invalid project name"):
        pc.load_projects(cfg)


def test_invalid_source_root_relative(tmp_path):
    cfg = write_yaml(
        tmp_path,
        """
        projects:
          - name: ace
            source_root: relative/path
    """,
    )
    with pytest.raises(ValueError, match="absolute"):
        pc.load_projects(cfg)


def test_explicit_missing_path_raises():
    with pytest.raises(FileNotFoundError):
        pc.load_projects("/nonexistent/path/projects.yaml")


# ---------------------------------------------------------------------------
# Backend semantics + output contract
# ---------------------------------------------------------------------------


def test_dense_collection_precedence(tmp_path):
    src = tmp_path / "src"
    inc = src / "frameworks" / "base"
    inc.mkdir(parents=True)

    cfg = write_yaml(
        tmp_path,
        f"""
        projects:
          - name: ace
            source_root: {src}
            collection_name: top_collection
            dense_index:
              collection_name: dense_collection
              include:
                - frameworks/base
        """,
    )

    payload = pc.build_backend_config("dense", config_path=cfg)
    project = payload["projects"][0]
    assert project["collection_name"] == "dense_collection"
    assert project["mode"] == "explicit"
    assert project["includes"][0]["repo_name"] == "frameworks/base"


def test_graph_omits_collection_name(tmp_path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    cfg = write_yaml(
        tmp_path,
        f"""
        projects:
          - name: ace
            source_root: {src}
        """,
    )

    payload = pc.build_backend_config("graph", config_path=cfg)
    project = payload["projects"][0]
    assert "collection_name" not in project
    assert project["mode"] == "default"


def test_backend_enabled_false_disables(tmp_path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    cfg = write_yaml(
        tmp_path,
        f"""
        projects:
          - name: ace
            source_root: {src}
            dense_index:
              enabled: false
        """,
    )

    payload = pc.build_backend_config("dense", config_path=cfg)
    project = payload["projects"][0]
    assert project["mode"] == "disabled"
    assert project["includes"] == []


def test_backend_include_empty_disables(tmp_path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    cfg = write_yaml(
        tmp_path,
        f"""
        projects:
          - name: ace
            source_root: {src}
            graph_index:
              include: []
        """,
    )

    payload = pc.build_backend_config("graph", config_path=cfg)
    project = payload["projects"][0]
    assert project["mode"] == "disabled"
    assert project["includes"] == []


def test_backend_enabled_false_with_include_errors(tmp_path):
    src = tmp_path / "src"
    (src / "frameworks" / "base").mkdir(parents=True)
    cfg = write_yaml(
        tmp_path,
        f"""
        projects:
          - name: ace
            source_root: {src}
            dense_index:
              enabled: false
              include:
                - frameworks/base
        """,
    )

    with pytest.raises(ValueError, match="enabled=false"):
        pc.build_backend_config("dense", config_path=cfg)


def test_mixing_legacy_and_backend_include_errors(tmp_path):
    src = tmp_path / "src"
    (src / "frameworks" / "base").mkdir(parents=True)
    cfg = write_yaml(
        tmp_path,
        f"""
        projects:
          - name: ace
            source_root: {src}
            sub_project_globs:
              - frameworks/*
            dense_index:
              include:
                - frameworks/base
        """,
    )

    with pytest.raises(ValueError, match="cannot mix sub_project_globs"):
        pc.build_backend_config("dense", config_path=cfg)


def test_include_validation_rejects_absolute(tmp_path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    cfg = write_yaml(
        tmp_path,
        f"""
        projects:
          - name: ace
            source_root: {src}
            graph_index:
              include:
                - /abs/path
        """,
    )

    with pytest.raises(ValueError, match="must be relative"):
        pc.build_backend_config("graph", config_path=cfg)


def test_include_validation_rejects_no_matches(tmp_path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    cfg = write_yaml(
        tmp_path,
        f"""
        projects:
          - name: ace
            source_root: {src}
            dense_index:
              include:
                - frameworks/*
        """,
    )

    with pytest.raises(ValueError, match="matched no paths"):
        pc.build_backend_config("dense", config_path=cfg)


def test_include_validation_rejects_file_match(tmp_path):
    src = tmp_path / "src"
    file_path = src / "frameworks" / "base" / "Android.bp"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("cc_library")

    cfg = write_yaml(
        tmp_path,
        f"""
        projects:
          - name: ace
            source_root: {src}
            dense_index:
              include:
                - frameworks/base/Android.bp
        """,
    )

    with pytest.raises(ValueError, match="matched non-directory"):
        pc.build_backend_config("dense", config_path=cfg)


def test_include_validation_rejects_symlink_escape(tmp_path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (src / "escape").symlink_to(outside, target_is_directory=True)

    cfg = write_yaml(
        tmp_path,
        f"""
        projects:
          - name: ace
            source_root: {src}
            graph_index:
              include:
                - escape
        """,
    )

    with pytest.raises(ValueError, match="outside source_root"):
        pc.build_backend_config("graph", config_path=cfg)


def test_include_deduplicates_repo_names(tmp_path):
    src = tmp_path / "src"
    inc = src / "frameworks" / "base"
    inc.mkdir(parents=True)

    cfg = write_yaml(
        tmp_path,
        f"""
        projects:
          - name: ace
            source_root: {src}
            dense_index:
              include:
                - frameworks/base
                - frameworks/*
        """,
    )

    with pytest.raises(ValueError, match="duplicate include repo_name"):
        pc.build_backend_config("dense", config_path=cfg)


def test_include_output_is_sorted_by_repo_name(tmp_path):
    src = tmp_path / "src"
    (src / "frameworks" / "zeta").mkdir(parents=True)
    (src / "frameworks" / "alpha").mkdir(parents=True)

    cfg = write_yaml(
        tmp_path,
        f"""
        projects:
          - name: ace
            source_root: {src}
            dense_index:
              include:
                - frameworks/*
        """,
    )

    payload = pc.build_backend_config("dense", config_path=cfg)
    repo_names = [it["repo_name"] for it in payload["projects"][0]["includes"]]
    assert repo_names == ["frameworks/alpha", "frameworks/zeta"]


def test_project_filter(tmp_path):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    cfg = write_yaml(
        tmp_path,
        f"""
        projects:
          - name: ace
            source_root: {src}
          - name: beta
            source_root: {src}
        """,
    )

    payload = pc.build_backend_config("graph", config_path=cfg, project="beta")
    assert [p["name"] for p in payload["projects"]] == ["beta"]


def test_cli_json_output(tmp_path, monkeypatch, capsys):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    cfg = write_yaml(
        tmp_path,
        f"""
        projects:
          - name: ace
            source_root: {src}
            dense_index:
              enabled: false
        """,
    )

    monkeypatch.setenv("PROJECTS_CONFIG_PATH", cfg)
    monkeypatch.setattr(
        "sys.argv",
        ["project_config.py", "--format", "json", "--backend", "dense"],
    )

    rc = pc.main()
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["backend"] == "dense"
    assert payload["projects"][0]["mode"] == "disabled"


def test_cli_unknown_project_returns_error(tmp_path, monkeypatch, capsys):
    src = tmp_path / "src"
    src.mkdir(parents=True)
    cfg = write_yaml(
        tmp_path,
        f"""
        projects:
          - name: ace
            source_root: {src}
        """,
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "project_config.py",
            "--format",
            "json",
            "--backend",
            "graph",
            "--config",
            cfg,
            "--project",
            "missing",
        ],
    )

    rc = pc.main()
    err = capsys.readouterr().err
    assert rc == 1
    assert "Unknown project" in err
