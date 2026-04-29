"""Tests for scripts/share/_env.sh."""

from __future__ import annotations

from pathlib import Path


def _env_preamble(proj_root: Path, tmp_dir: Path) -> str:
    """Source _common.sh then override PROJ_ROOT before sourcing _env.sh."""
    return f"""
        source "{proj_root}/scripts/share/_common.sh"
        PROJ_ROOT="{tmp_dir}"
    """


def test_basic_load(run_bash, proj_root, tmp_dir):
    """Default behavior: loads .env and sets vars."""
    dotenv = tmp_dir / ".env"
    dotenv.write_text("FOO=hello\nBAR=world\n")
    r = run_bash(
        _env_preamble(proj_root, tmp_dir)
        + f"""
        source "{proj_root}/scripts/share/_env.sh"
        echo "FOO=$FOO"
        echo "BAR=$BAR"
        """,
    )
    assert r.returncode == 0
    assert "FOO=hello" in r.stdout
    assert "BAR=world" in r.stdout


def test_env_precedence(run_bash, proj_root, tmp_dir):
    """Environment variables take precedence over .env values."""
    dotenv = tmp_dir / ".env"
    dotenv.write_text("FOO=from_file\n")
    r = run_bash(
        _env_preamble(proj_root, tmp_dir)
        + f"""
        export FOO=from_env
        source "{proj_root}/scripts/share/_env.sh"
        echo "FOO=$FOO"
        """,
        env={"FOO": "from_env"},
    )
    assert r.returncode == 0
    assert "FOO=from_env" in r.stdout


def test_source_guard_idempotent(run_bash, proj_root, tmp_dir):
    """Sourcing twice is idempotent — second source is a no-op."""
    dotenv = tmp_dir / ".env"
    dotenv.write_text("FOO=first\n")
    r = run_bash(
        _env_preamble(proj_root, tmp_dir)
        + f"""
        source "{proj_root}/scripts/share/_env.sh"
        unset FOO
        source "{proj_root}/scripts/share/_env.sh"
        echo "FOO=${{FOO:-UNSET}}"
        """,
    )
    assert r.returncode == 0
    assert "FOO=UNSET" in r.stdout


def test_no_autoload(run_bash, proj_root, tmp_dir):
    """SOURCEPILOT_ENV_NO_AUTOLOAD=1 defines function but doesn't load."""
    dotenv = tmp_dir / ".env"
    dotenv.write_text("FOO=bar\n")
    r = run_bash(
        _env_preamble(proj_root, tmp_dir)
        + f"""
        export SOURCEPILOT_ENV_NO_AUTOLOAD=1
        source "{proj_root}/scripts/share/_env.sh"
        echo "BEFORE=${{FOO:-UNSET}}"
        load_env_file
        echo "AFTER=$FOO"
        """,
        env={"SOURCEPILOT_ENV_NO_AUTOLOAD": "1"},
    )
    assert r.returncode == 0
    assert "BEFORE=UNSET" in r.stdout
    assert "AFTER=bar" in r.stdout


def test_quiet_mode(run_bash, proj_root, tmp_dir):
    """SOURCEPILOT_ENV_QUIET=1 suppresses stderr message."""
    dotenv = tmp_dir / ".env"
    dotenv.write_text("X=1\n")
    r = run_bash(
        _env_preamble(proj_root, tmp_dir)
        + f"""
        export SOURCEPILOT_ENV_QUIET=1
        source "{proj_root}/scripts/share/_env.sh"
        """,
        env={"SOURCEPILOT_ENV_QUIET": "1"},
    )
    assert r.returncode == 0
    assert "Loaded config" not in r.stderr


def test_non_quiet_default(run_bash, proj_root, tmp_dir):
    """Default behavior prints 'Loaded config' to stderr."""
    dotenv = tmp_dir / ".env"
    dotenv.write_text("X=1\n")
    r = run_bash(
        _env_preamble(proj_root, tmp_dir)
        + f"""
        source "{proj_root}/scripts/share/_env.sh"
        """,
    )
    assert r.returncode == 0
    assert "Loaded config" in r.stderr


def test_load_env_file_custom_path(run_bash, proj_root, tmp_dir):
    """load_env_file() accepts a custom path argument."""
    custom = tmp_dir / "custom.env"
    custom.write_text("CUSTOM_VAR=yes\n")
    r = run_bash(
        _env_preamble(proj_root, tmp_dir)
        + f"""
        export SOURCEPILOT_ENV_NO_AUTOLOAD=1
        source "{proj_root}/scripts/share/_env.sh"
        load_env_file "{custom}"
        echo "CUSTOM_VAR=$CUSTOM_VAR"
        """,
        env={"SOURCEPILOT_ENV_NO_AUTOLOAD": "1"},
    )
    assert r.returncode == 0
    assert "CUSTOM_VAR=yes" in r.stdout


def test_missing_env_file(run_bash, proj_root, tmp_dir):
    """No .env file is not an error."""
    r = run_bash(
        _env_preamble(proj_root, tmp_dir)
        + f"""
        source "{proj_root}/scripts/share/_env.sh"
        echo "OK"
        """,
    )
    assert r.returncode == 0
    assert "OK" in r.stdout


def test_quoted_values(run_bash, proj_root, tmp_dir):
    """Quoted values are parsed correctly."""
    dotenv = tmp_dir / ".env"
    dotenv.write_text('DQ="double quoted"\nSQ=\'single quoted\'\n')
    r = run_bash(
        _env_preamble(proj_root, tmp_dir)
        + f"""
        source "{proj_root}/scripts/share/_env.sh"
        echo "DQ=$DQ"
        echo "SQ=$SQ"
        """,
    )
    assert r.returncode == 0
    assert "DQ=double quoted" in r.stdout
    assert "SQ=single quoted" in r.stdout
