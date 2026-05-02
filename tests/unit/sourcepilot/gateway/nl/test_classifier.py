"""
Unit tests for classify_query()

Covers Zoekt modifiers, regex patterns, NL indicators, mixed Chinese/English,
pure symbol paths, and length threshold branches.
"""

import pytest
from gateway.nl.classifier import classify_query


# ─── Zoekt modifiers → exact ─────────────────────────────────────────────────

class TestZoektModifiers:
    """Zoekt prefix modifiers must route as exact."""

    def test_sym_prefix(self):
        assert classify_query("sym:ActivityManager") == "exact"

    def test_file_prefix(self):
        assert classify_query("file:build.gradle") == "exact"

    def test_r_prefix(self):
        assert classify_query("r:framework") == "exact"

    def test_lang_prefix(self):
        assert classify_query("lang:java foo") == "exact"

    def test_case_prefix(self):
        assert classify_query("case:yes foo") == "exact"


# ─── Regex pattern → exact ──────────────────────────────────────────────────

class TestRegexPattern:
    """r"..." format is identified as exact (regex query)."""

    def test_regex_pattern(self):
        assert classify_query('r"pattern"') == "exact"

    def test_regex_with_content(self):
        assert classify_query('r"ActivityManager.*start"') == "exact"


# ─── NL Chinese keywords → natural_language ──────────────────────────────────

class TestNLChineseKeywords:
    """Queries containing NL Chinese keywords must route as natural_language."""

    def test_zenme(self):
        # "怎么" is in the keyword list
        assert classify_query("怎么实现xxx") == "natural_language"

    def test_shenme(self):
        assert classify_query("什么是SystemServer") == "natural_language"

    def test_ruhe(self):
        assert classify_query("如何启动一个Activity") == "natural_language"

    def test_weishenme(self):
        assert classify_query("为什么会崩溃") == "natural_language"

    def test_qidong(self):
        # "启动" is in the NL keyword list
        assert classify_query("启动流程是什么") == "natural_language"

    def test_shixian(self):
        # "实现" is in the NL keyword list
        assert classify_query("ActivityManager实现原理") == "natural_language"


# ─── NL English keywords → natural_language ──────────────────────────────────

class TestNLEnglishKeywords:
    """Queries containing NL English keywords must route as natural_language."""

    def test_how(self):
        assert classify_query("how to start activity") == "natural_language"

    def test_what(self):
        assert classify_query("what is SystemServer") == "natural_language"

    def test_explain(self):
        assert classify_query("explain the flow") == "natural_language"

    def test_why(self):
        assert classify_query("why does this crash") == "natural_language"

    def test_where(self):
        assert classify_query("where is init.rc loaded") == "natural_language"

    def test_find(self):
        assert classify_query("find all Activity classes") == "natural_language"

    def test_describe(self):
        assert classify_query("describe the boot process") == "natural_language"


# ─── Mixed Chinese + code identifier → natural_language ──────────────────────

class TestChineseCodeMix:
    """Chinese characters + code identifier combination triggers the NL branch (even without NL indicator words)."""

    def test_chinese_plus_camelcase(self):
        # has_chinese=True, has_code=True (ActivityManager has 3+ trailing chars)
        assert classify_query("ActivityManager是什么") == "natural_language"

    def test_chinese_plus_dotted_identifier(self):
        # "ro.vendor.tags" has an identifier with 4+ chars
        assert classify_query("ro.vendor.tags有哪些引用") == "natural_language"


# ─── Pure symbol/path → exact ─────────────────────────────────────────────────

class TestPureSymbolPath:
    """Only alphanumeric characters, dots, underscores, slashes, colons, hyphens → exact."""

    def test_camelcase_symbol(self):
        # "SystemServer" contains only letters → exact (no NL words, no Chinese)
        assert classify_query("SystemServer") == "exact"

    def test_java_package(self):
        assert classify_query("com.android.server") == "exact"

    def test_unix_path(self):
        assert classify_query("frameworks/base/core") == "exact"

    def test_init_rc(self):
        assert classify_query("init.rc") == "exact"

    def test_hyphen_path(self):
        assert classify_query("build-tools") == "exact"


# ─── Length threshold → natural_language ─────────────────────────────────────

class TestLengthThreshold:
    """Pure ASCII with no NL keywords but longer than 15 characters is classified as natural_language."""

    def test_long_sentence(self):
        # length exceeds 15, no NL keywords, has spaces (doesn't match pure-symbol regex)
        q = "this is a long query string that exceeds fifteen chars"
        assert classify_query(q) == "natural_language"

    def test_exactly_16_chars_with_space(self):
        # 16 characters, contains space (doesn't match pure-symbol path regex)
        q = "a b c d e f g h i"  # len > 15
        assert classify_query(q) == "natural_language"

    def test_short_exact(self):
        # ≤15 chars, no Chinese, no NL keywords, contains space → exact (hits final return 'exact')
        # "init.rc" matches the pure-symbol path regex
        assert classify_query("init.rc") == "exact"


# ─── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Empty string, whitespace-only, and similar boundary inputs."""

    def test_empty_string(self):
        # strip() results in empty string; no branch matches; final return is exact
        assert classify_query("") == "exact"

    def test_whitespace_only(self):
        # strip() results in empty string; same as above
        assert classify_query("   ") == "exact"

    def test_leading_trailing_whitespace(self):
        # leading/trailing whitespace but content is an exact symbol
        assert classify_query("  SystemServer  ") == "exact"
