"""Unit tests for scripts/indexing/project_config.py"""

import os
import textwrap

import pytest

import project_config as pc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_yaml(tmp_path, content: str):
    p = tmp_path / "projects.yaml"
    p.write_text(textwrap.dedent(content))
    return str(p)


# ---------------------------------------------------------------------------
# YAML parsing
# ---------------------------------------------------------------------------

def test_yaml_minimal(tmp_path):
    cfg = write_yaml(tmp_path, """
        projects:
          - name: ace
            source_root: /mnt/code/ACE
    """)
    projects = pc.load_projects(cfg)
    assert len(projects) == 1
    p = projects[0]
    assert p["name"] == "ace"
    assert p["source_root"] == "/mnt/code/ACE"
    assert p["collection_name"] == "aosp_code_ace"
    assert p["sub_project_globs"] == []


def test_yaml_collection_name_override(tmp_path):
    cfg = write_yaml(tmp_path, """
        projects:
          - name: aosp15
            source_root: /mnt/code/AOSP15
            collection_name: my_custom_collection
    """)
    projects = pc.load_projects(cfg)
    assert projects[0]["collection_name"] == "my_custom_collection"


def test_yaml_sub_project_globs(tmp_path):
    cfg = write_yaml(tmp_path, """
        projects:
          - name: ace
            source_root: /mnt/code/ACE
            sub_project_globs:
              - frameworks/*
              - system/core/*
    """)
    projects = pc.load_projects(cfg)
    assert projects[0]["sub_project_globs"] == ["frameworks/*", "system/core/*"]


def test_yaml_two_projects(tmp_path):
    cfg = write_yaml(tmp_path, """
        projects:
          - name: ace
            source_root: /mnt/code/ACE
          - name: aosp15
            source_root: /mnt/code/AOSP15
    """)
    projects = pc.load_projects(cfg)
    assert len(projects) == 2
    assert {p["name"] for p in projects} == {"ace", "aosp15"}


# ---------------------------------------------------------------------------
# Fallback behaviour
# ---------------------------------------------------------------------------

def test_fallback_uses_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AOSP_SOURCE_ROOT", "/mnt/code/MY_PROJECT")
    # Point load_projects at a non-existent default (no YAML in a fresh tmp dir)
    # by temporarily overriding _PROJ_ROOT so no projects.yaml is found
    monkeypatch.setattr(pc, "_PROJ_ROOT", tmp_path)
    projects = pc.load_projects()
    assert len(projects) == 1
    assert projects[0]["source_root"] == "/mnt/code/MY_PROJECT"
    assert projects[0]["name"] == "my_project"
    assert projects[0]["collection_name"] == "aosp_code_my_project"


def test_fallback_default_source_root(monkeypatch, tmp_path):
    monkeypatch.delenv("AOSP_SOURCE_ROOT", raising=False)
    monkeypatch.setattr(pc, "_PROJ_ROOT", tmp_path)
    projects = pc.load_projects()
    assert projects[0]["source_root"] == "/mnt/code/ACE"


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------

def test_invalid_name_uppercase(tmp_path):
    cfg = write_yaml(tmp_path, """
        projects:
          - name: ACE
            source_root: /mnt/code/ACE
    """)
    with pytest.raises(ValueError, match="Invalid project name"):
        pc.load_projects(cfg)


def test_invalid_name_spaces(tmp_path):
    cfg = write_yaml(tmp_path, """
        projects:
          - name: "foo bar"
            source_root: /mnt/code/ACE
    """)
    with pytest.raises(ValueError, match="Invalid project name"):
        pc.load_projects(cfg)


def test_invalid_name_hyphen(tmp_path):
    cfg = write_yaml(tmp_path, """
        projects:
          - name: foo-bar
            source_root: /mnt/code/ACE
    """)
    with pytest.raises(ValueError, match="Invalid project name"):
        pc.load_projects(cfg)


def test_invalid_source_root_relative(tmp_path):
    cfg = write_yaml(tmp_path, """
        projects:
          - name: ace
            source_root: relative/path
    """)
    with pytest.raises(ValueError, match="absolute"):
        pc.load_projects(cfg)


# ---------------------------------------------------------------------------
# Missing config_path
# ---------------------------------------------------------------------------

def test_explicit_missing_path_raises():
    with pytest.raises(FileNotFoundError):
        pc.load_projects("/nonexistent/path/projects.yaml")
