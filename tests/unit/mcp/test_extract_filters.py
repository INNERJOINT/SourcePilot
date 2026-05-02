"""Unit tests for _extract_filters() in entry.handlers."""

from entry.handlers import _extract_filters


def test_empty_args_returns_defaults():
    result = _extract_filters({})
    assert result["lang"] is None
    assert result["branch"] is None
    assert result["case_sensitive"] == "auto"
    assert "project" not in result


def test_empty_string_project_not_propagated():
    result = _extract_filters({"project": ""})
    assert "project" not in result


def test_valid_project_propagated():
    result = _extract_filters({"project": "aosp-14"})
    assert result["project"] == "aosp-14"


def test_none_lang_is_not_string_none():
    result = _extract_filters({"lang": None})
    assert result["lang"] is None
    assert result["lang"] != "None"


def test_case_sensitive_yes_carried_through():
    result = _extract_filters({"case_sensitive": "yes"})
    assert result["case_sensitive"] == "yes"
