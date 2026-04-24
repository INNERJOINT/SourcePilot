"""
Tests for Feishu ingestion chunker (build_feishu_index.py).
No live services required.
"""

import hashlib
import sys
from pathlib import Path

import pytest

# Add scripts/indexing to sys.path so we can import the module directly
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "indexing"))

from build_feishu_index import text_sliding_window_chunks


class TestTextSlidingWindowChunks:
    def test_basic_chunking(self):
        """Basic sliding window with known offsets."""
        content = "abcdefghij"  # len=10
        chunks = text_sliding_window_chunks(
            content=content,
            title="T",
            url="http://x",
            space_id="s1",
            node_token="n1",
            window_size=5,
            overlap=2,
        )
        # step = 5 - 2 = 3
        # start=0 -> "abcde", start=3 -> "defgh", start=6 -> "ghij"
        assert len(chunks) == 3
        assert chunks[0]["content"] == "abcde"
        assert chunks[1]["content"] == "defgh"
        assert chunks[2]["content"] == "ghij"

    def test_empty_content_returns_empty(self):
        chunks = text_sliding_window_chunks(
            content="",
            title="T",
            url="http://x",
            space_id="s1",
            node_token="n1",
        )
        assert chunks == []

    def test_whitespace_only_content_returns_empty(self):
        chunks = text_sliding_window_chunks(
            content="   \n\t  ",
            title="T",
            url="http://x",
            space_id="s1",
            node_token="n1",
        )
        assert chunks == []

    def test_metadata_propagated_to_each_chunk(self):
        content = "hello world"
        chunks = text_sliding_window_chunks(
            content=content,
            title="My Doc",
            url="http://feishu/doc/123",
            space_id="sp_abc",
            node_token="nt_xyz",
            window_size=6,
            overlap=0,
        )
        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk["title"] == "My Doc"
            assert chunk["url"] == "http://feishu/doc/123"
            assert chunk["space_id"] == "sp_abc"
            assert chunk["node_token"] == "nt_xyz"

    def test_content_hash_is_md5(self):
        content = "test content"
        chunks = text_sliding_window_chunks(
            content=content,
            title="T",
            url="u",
            space_id="s",
            node_token="n",
            window_size=100,
            overlap=0,
        )
        assert len(chunks) == 1
        expected_hash = hashlib.md5(content.encode()).hexdigest()
        assert chunks[0]["content_hash"] == expected_hash

    def test_content_shorter_than_window_produces_single_chunk(self):
        content = "short"
        chunks = text_sliding_window_chunks(
            content=content,
            title="T",
            url="u",
            space_id="s",
            node_token="n",
            window_size=500,
            overlap=100,
        )
        assert len(chunks) == 1
        assert chunks[0]["content"] == "short"

    def test_no_overlap(self):
        content = "abcdef"
        chunks = text_sliding_window_chunks(
            content=content,
            title="T",
            url="u",
            space_id="s",
            node_token="n",
            window_size=3,
            overlap=0,
        )
        assert len(chunks) == 2
        assert chunks[0]["content"] == "abc"
        assert chunks[1]["content"] == "def"

    def test_chunk_dict_has_required_keys(self):
        chunks = text_sliding_window_chunks(
            content="some text here",
            title="Doc",
            url="http://u",
            space_id="sp",
            node_token="nt",
        )
        required_keys = {"content", "title", "url", "space_id", "node_token", "content_hash"}
        for chunk in chunks:
            assert required_keys.issubset(chunk.keys())
