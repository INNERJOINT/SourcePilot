"""Unit tests for scripts/generate_compose.py."""

import sys
from pathlib import Path

import pytest
import yaml

# Add scripts/ to path so we can import the generator
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from generate_compose import (
    build_gateway_service,
    build_zoekt_services,
    expand,
    generate,
    is_stale,
    load_dotenv,
    load_projects,
    main,
)


@pytest.fixture
def single_project_yaml(tmp_path):
    p = tmp_path / "projects.yaml"
    p.write_text(
        yaml.dump(
            {
                "projects": [
                    {
                        "name": "ace",
                        "source_root": "/mnt/code/ACE",
                        "repo_path": "/mnt/code/ACE/.repo",
                        "sparse_index": {
                            "index_dir": "/mnt/code/ACE/.repo/.zoekt",
                            "zoekt_url": "http://sparse-index-zoekt:6070",
                        },
                    }
                ]
            }
        )
    )
    return p


@pytest.fixture
def multi_project_yaml(tmp_path):
    p = tmp_path / "projects.yaml"
    p.write_text(
        yaml.dump(
            {
                "projects": [
                    {
                        "name": "ace",
                        "source_root": "/mnt/code/ACE",
                        "repo_path": "/mnt/code/ACE/.repo",
                        "sparse_index": {
                            "index_dir": "/mnt/code/ACE/.repo/.zoekt",
                            "zoekt_url": "http://sparse-index-zoekt:6070",
                        },
                    },
                    {
                        "name": "t2",
                        "source_root": "/opt/aosp/t2",
                        "repo_path": "/opt/aosp/t2/.repo",
                        "sparse_index": {
                            "index_dir": "/opt/aosp/t2/.repo/.zoekt",
                            "zoekt_url": "http://sparse-index-zoekt-t2:6070",
                        },
                    },
                ]
            }
        )
    )
    return p


@pytest.fixture
def multi_zoekt_yaml(tmp_path):
    p = tmp_path / "projects.yaml"
    p.write_text(
        yaml.dump(
            {
                "projects": [
                    {
                        "name": "ace",
                        "source_root": "/mnt/code/ACE",
                        "repo_path": "/mnt/code/ACE/.repo",
                        "sparse_index": {
                            "zoekt_urls": {
                                "sys": "http://sparse-index-zoekt-ace-sys:6070",
                                "vnd": "http://sparse-index-zoekt-ace-vnd:6070",
                            },
                            "index_dirs": {
                                "sys": "/mnt/code/ACE-sys/.zoekt",
                                "vnd": "/mnt/code/ACE-vnd/.zoekt",
                            },
                        },
                    }
                ]
            }
        )
    )
    return p


@pytest.fixture
def dot_env(tmp_path):
    p = tmp_path / ".env"
    p.write_text("ZOEKT_PORT=6070\nSOURCEPILOT_PORT=9000\nMCP_PORT=8888\n")
    return p


class TestExpand:
    def test_basic(self):
        assert expand("${FOO:-bar}", {"FOO": "baz"}) == "baz"

    def test_default(self):
        assert expand("${FOO:-bar}", {}) == "bar"

    def test_no_default(self):
        assert expand("${FOO}", {}) == ""

    def test_multiple(self):
        assert expand("${A:-1}:${B:-2}", {"A": "x"}) == "x:2"

    def test_no_var(self):
        assert expand("plain", {}) == "plain"


class TestLoadDotenv:
    def test_basic(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MY_TEST_VAR", raising=False)
        p = tmp_path / ".env"
        p.write_text("MY_TEST_VAR=hello\n")
        env = load_dotenv(p)
        assert env["MY_TEST_VAR"] == "hello"

    def test_env_precedence(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_TEST_VAR", "from_env")
        p = tmp_path / ".env"
        p.write_text("MY_TEST_VAR=from_file\n")
        env = load_dotenv(p)
        assert env["MY_TEST_VAR"] == "from_env"

    def test_missing_file(self, tmp_path):
        env = load_dotenv(tmp_path / "nonexistent")
        assert isinstance(env, dict)


class TestBuildZoektServices:
    def test_single_project(self, single_project_yaml):
        projects = load_projects(single_project_yaml)
        env = {"ZOEKT_PORT": "6070"}
        svcs = build_zoekt_services(projects, env)
        assert "sparse-index-zoekt" in svcs
        assert svcs["sparse-index-zoekt"]["ports"] == ["6070:6070"]

    def test_multi_project(self, multi_project_yaml):
        projects = load_projects(multi_project_yaml)
        env = {"ZOEKT_PORT": "6070", "ZOEKT_PORT_T2": "6071"}
        svcs = build_zoekt_services(projects, env)
        assert "sparse-index-zoekt" in svcs
        assert "sparse-index-zoekt-t2" in svcs
        assert svcs["sparse-index-zoekt-t2"]["ports"] == ["6071:6070"]

    def test_multi_zoekt(self, multi_zoekt_yaml):
        projects = load_projects(multi_zoekt_yaml)
        env = {"ZOEKT_PORT_ACE_SYS": "6072", "ZOEKT_PORT_ACE_VND": "6073"}
        svcs = build_zoekt_services(projects, env)
        assert "sparse-index-zoekt-ace-sys" in svcs
        assert "sparse-index-zoekt-ace-vnd" in svcs


class TestGatewayEnv:
    def test_zoekt_url_vars(self, multi_project_yaml):
        projects = load_projects(multi_project_yaml)
        env = {}
        gw = build_gateway_service(projects, env)
        gw_env = gw["environment"]
        assert gw_env["ZOEKT_URL_ACE"] == "http://sparse-index-zoekt:6070"
        assert gw_env["ZOEKT_URL_T2"] == "http://sparse-index-zoekt-t2:6070"
        assert gw_env["ZOEKT_URL"] == "http://sparse-index-zoekt:6070"

    def test_multi_zoekt_env(self, multi_zoekt_yaml):
        projects = load_projects(multi_zoekt_yaml)
        env = {}
        gw = build_gateway_service(projects, env)
        gw_env = gw["environment"]
        assert gw_env["ZOEKT_URL_ACE_SYS"] == "http://sparse-index-zoekt-ace-sys:6070"
        assert gw_env["ZOEKT_URL_ACE_VND"] == "http://sparse-index-zoekt-ace-vnd:6070"


class TestGenerate:
    def test_full_output(self, single_project_yaml):
        projects = load_projects(single_project_yaml)
        env = {"ZOEKT_PORT": "6070", "SOURCEPILOT_PORT": "9000"}
        compose = generate(projects, env)
        assert compose["name"] == "sourcepilot"
        assert "sourcepilot-gateway" in compose["services"]
        assert "qdrant" in compose["services"]
        assert "neo4j" in compose["services"]
        assert "mcp-server" in compose["services"]
        assert "sourcepilot-net" in compose["networks"]

    def test_no_dollar_refs_in_output(self, single_project_yaml):
        projects = load_projects(single_project_yaml)
        env = {"ZOEKT_PORT": "6070"}
        compose = generate(projects, env)
        rendered = yaml.dump(compose)
        assert "${" not in rendered

    def test_valid_yaml_roundtrip(self, single_project_yaml):
        projects = load_projects(single_project_yaml)
        compose = generate(projects, {})
        text = yaml.dump(compose, default_flow_style=False, sort_keys=False)
        reloaded = yaml.safe_load(text)
        assert reloaded["name"] == "sourcepilot"


class TestMain:
    def test_generates_file(self, single_project_yaml, dot_env, tmp_path):
        output = tmp_path / "docker-compose.yml"
        rc = main([
            "--projects-config", str(single_project_yaml),
            "--env-file", str(dot_env),
            "--output", str(output),
        ])
        assert rc == 0
        assert output.exists()
        content = output.read_text()
        assert "AUTO-GENERATED" in content
        loaded = yaml.safe_load(content)
        assert loaded["name"] == "sourcepilot"

    def test_empty_projects_fails(self, tmp_path):
        p = tmp_path / "projects.yaml"
        p.write_text("projects: []\n")
        output = tmp_path / "out.yml"
        with pytest.raises(ValueError, match="non-empty"):
            main([
                "--projects-config", str(p),
                "--env-file", str(tmp_path / ".env"),
                "--output", str(output),
            ])


class TestStaleness:
    def test_stale_when_missing(self, tmp_path):
        assert is_stale(
            tmp_path / "out.yml",
            tmp_path / "projects.yaml",
            tmp_path / ".env",
        )

    def test_stale_when_input_newer(self, tmp_path):
        out = tmp_path / "out.yml"
        cfg = tmp_path / "projects.yaml"
        out.write_text("old")
        import time
        time.sleep(0.05)
        cfg.write_text("new")
        assert is_stale(out, cfg, tmp_path / ".env")

    def test_not_stale(self, tmp_path):
        cfg = tmp_path / "projects.yaml"
        cfg.write_text("data")
        import time
        time.sleep(0.05)
        out = tmp_path / "out.yml"
        out.write_text("generated")
        assert not is_stale(out, cfg, tmp_path / ".env")
