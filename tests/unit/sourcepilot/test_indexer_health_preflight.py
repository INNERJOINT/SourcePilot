"""Unit tests for _preflight_check_active_code_model in build_dense_index."""

# Import the helper directly — script lives outside src/, load via importlib
import importlib.util
import logging
import pathlib
from unittest.mock import MagicMock, patch

import pytest

_script = (
    pathlib.Path(__file__).parents[3]
    / "scripts/indexing/dense/build_dense_index.py"
)
_spec = importlib.util.spec_from_file_location("build_dense_index", _script)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

preflight = _mod._preflight_check_active_code_model

_EMB_URL = "http://localhost:8080/v1"
_UNIX = "microsoft/unixcoder-base"
_CRE = "nomic-ai/CodeRankEmbed"
_COLL = "aosp_code_t2_dense_unixcoder"


def _mock_response(json_data: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


# a) /health returns active_code_model matching project → no abort
def test_matching_model_no_abort():
    resp = _mock_response({"active_code_model": _UNIX})
    with patch("httpx.get", return_value=resp):
        preflight(_EMB_URL, _UNIX, _COLL)


# b) /health returns active_code_model mismatched and project model in CODE_MODELS → SystemExit
def test_mismatched_model_raises():
    resp = _mock_response({"active_code_model": _CRE})
    with patch("httpx.get", return_value=resp):
        with pytest.raises(SystemExit) as exc_info:
            preflight(_EMB_URL, _UNIX, _COLL)
    assert "Embedding-server active_code_model=" in str(exc_info.value)


# c) /health returns 200 but no active_code_model field → no abort, INFO logged
def test_no_active_code_model_key_no_abort(caplog):
    resp = _mock_response({"status": "ok"})
    with patch("httpx.get", return_value=resp):
        with caplog.at_level(logging.INFO):
            preflight(_EMB_URL, _UNIX, _COLL)
    assert "skipping consistency check" in caplog.text


# d) /health unreachable → no abort, WARN logged
def test_unreachable_no_abort(caplog):
    with patch("httpx.get", side_effect=Exception("Connection refused")):
        with caplog.at_level(logging.WARNING):
            preflight(_EMB_URL, _UNIX, _COLL)
    assert "unreachable" in caplog.text
