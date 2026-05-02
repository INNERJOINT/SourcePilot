"""Schema-pin canary for SourcePilot /api/search response contract.

This test loads a hand-curated golden fixture representing a typical SourcePilot
search response and passes it through _format_results.  If this test breaks, audit
the SourcePilot /api/search response schema — something changed upstream.

Fixture: tests/fixtures/sourcepilot_search_response.json
"""

import json
from pathlib import Path

import pytest  # noqa: F401
from entry.handlers import _format_results

FIXTURE_PATH = Path(__file__).parent.parent.parent / "fixtures" / "sourcepilot_search_response.json"


@pytest.fixture
def search_response():
    return json.loads(FIXTURE_PATH.read_text())


def test_fixture_loads_expected_entries(search_response):
    assert len(search_response) == 3


def test_format_results_no_exception(search_response):
    """_format_results must not raise on the golden fixture."""
    result = _format_results("AudioFlinger", search_response)
    assert isinstance(result, str)


def test_format_results_full_entry_has_location(search_response):
    """First entry has start_line+end_line — expect (L100-L104) in output."""
    result = _format_results("AudioFlinger", search_response)
    assert "(L100-L104)" in result


def test_format_results_no_content_preview_omitted(search_response):
    """Second entry has '(no content preview available)' — must not appear in output."""
    result = _format_results("AudioFlinger", search_response)
    assert "(no content preview available)" not in result


def test_format_results_sparse_metadata_no_location_suffix(search_response):
    """Third entry lacks start_line/end_line — no (L..) suffix for that entry."""
    result = _format_results("AudioFlinger", search_response)
    # The third entry's path is audio_hw.c — its line in output should NOT have (L
    lines = result.splitlines()
    hw_lines = [line for line in lines if "audio_hw.c" in line]
    assert hw_lines, "audio_hw.c should appear in output"
    assert all("(L" not in line for line in hw_lines)
