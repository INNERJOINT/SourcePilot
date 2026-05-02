"""Unit tests for _format_results() in entry.handlers."""

from entry.handlers import _format_results


def test_empty_list_returns_not_found_message():
    result = _format_results("AudioTrack", [])
    assert result == 'No code found matching "AudioTrack".'


def test_result_missing_metadata_does_not_raise():
    """Result dict without 'metadata' key must not raise; falls back to title."""
    result = _format_results("foo", [{"title": "some/file.cpp", "content": "int x = 0;"}])
    assert "some/file.cpp" in result
    assert "foo" in result


def test_result_no_content_preview_omits_code_block():
    """Content '(no content preview available)' must be omitted from output."""
    result = _format_results(
        "bar",
        [
            {
                "title": "path/to/file.h",
                "content": "(no content preview available)",
                "metadata": {"repo": "platform/frameworks", "path": "path/to/file.h"},
            }
        ],
    )
    assert "(no content preview available)" not in result
    assert "```" not in result


def test_result_missing_start_end_line_omits_location_suffix():
    """Result with metadata but no start_line/end_line should have no '(L..)' suffix."""
    result = _format_results(
        "baz",
        [
            {
                "title": "core/main.c",
                "content": "void main() {}",
                "metadata": {"repo": "platform/core", "path": "core/main.c"},
            }
        ],
    )
    assert "(L" not in result


def test_result_with_all_fields_formats_correctly():
    """Full result should include fenced code block and (L<start>-L<end>) location."""
    result = _format_results(
        "AudioFlinger",
        [
            {
                "title": "AudioFlinger.cpp",
                "content": "class AudioFlinger {}",
                "metadata": {
                    "repo": "frameworks/av",
                    "path": "media/AudioFlinger.cpp",
                    "start_line": 42,
                    "end_line": 88,
                    "score": 0.95,
                },
            }
        ],
    )
    assert "(L42-L88)" in result
    assert "```" in result
    assert "class AudioFlinger {}" in result
    assert "frameworks/av" in result
