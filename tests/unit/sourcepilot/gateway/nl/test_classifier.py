"""
classify_query() 单元测试

覆盖 Zoekt 修饰符、正则、NL 指示词、中英文混合、纯符号路径、长度阈值等分支。
"""

import pytest
from gateway.nl.classifier import classify_query


# ─── Zoekt 修饰符 → exact ────────────────────────────────────────────────────

class TestZoektModifiers:
    """Zoekt 前缀修饰符必须路由为 exact。"""

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


# ─── 正则表达式 → exact ──────────────────────────────────────────────────────

class TestRegexPattern:
    """r"..." 格式识别为 exact（正则查询）。"""

    def test_regex_pattern(self):
        assert classify_query('r"pattern"') == "exact"

    def test_regex_with_content(self):
        assert classify_query('r"ActivityManager.*start"') == "exact"


# ─── NL 中文指示词 → natural_language ────────────────────────────────────────

class TestNLChineseKeywords:
    """含 NL 中文关键词的查询必须路由为 natural_language。"""

    def test_zenme(self):
        # "怎么" 在列表中
        assert classify_query("怎么实现xxx") == "natural_language"

    def test_shenme(self):
        assert classify_query("什么是SystemServer") == "natural_language"

    def test_ruhe(self):
        assert classify_query("如何启动一个Activity") == "natural_language"

    def test_weishenme(self):
        assert classify_query("为什么会崩溃") == "natural_language"

    def test_qidong(self):
        # "启动" 在 NL 词列表中
        assert classify_query("启动流程是什么") == "natural_language"

    def test_shixian(self):
        # "实现" 在 NL 词列表中
        assert classify_query("ActivityManager实现原理") == "natural_language"


# ─── NL 英文指示词 → natural_language ────────────────────────────────────────

class TestNLEnglishKeywords:
    """含 NL 英文关键词的查询必须路由为 natural_language。"""

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


# ─── 中文 + 代码标识符混合 → natural_language ────────────────────────────────

class TestChineseCodeMix:
    """中文字符 + 代码标识符组合触发 NL 分支（即使没有 NL 指示词）。"""

    def test_chinese_plus_camelcase(self):
        # has_chinese=True, has_code=True（ActivityManager >= 3 个后续字符）
        assert classify_query("ActivityManager是什么") == "natural_language"

    def test_chinese_plus_dotted_identifier(self):
        # "ro.seewo.tags" 有 4+ 个字符的标识符
        assert classify_query("ro.seewo.tags有哪些引用") == "natural_language"


# ─── 纯符号/路径 → exact ─────────────────────────────────────────────────────

class TestPureSymbolPath:
    """仅含字母数字点下划线斜杠冒号连字符 → exact。"""

    def test_camelcase_symbol(self):
        # "SystemServer" 仅含字母 → exact（无 NL 词，无中文）
        assert classify_query("SystemServer") == "exact"

    def test_java_package(self):
        assert classify_query("com.android.server") == "exact"

    def test_unix_path(self):
        assert classify_query("frameworks/base/core") == "exact"

    def test_init_rc(self):
        assert classify_query("init.rc") == "exact"

    def test_hyphen_path(self):
        assert classify_query("build-tools") == "exact"


# ─── 长度阈值 → natural_language ─────────────────────────────────────────────

class TestLengthThreshold:
    """纯 ASCII 无 NL 词但超过 15 字符的查询判为 natural_language。"""

    def test_long_sentence(self):
        # 长度超过 15，无 NL 关键词，有空格（不满足纯符号正则）
        q = "this is a long query string that exceeds fifteen chars"
        assert classify_query(q) == "natural_language"

    def test_exactly_16_chars_with_space(self):
        # 16 字符、含空格（不满足纯符号路径正则）
        q = "a b c d e f g h i"  # len > 15
        assert classify_query(q) == "natural_language"

    def test_short_exact(self):
        # ≤15 字符、无中文无 NL 词、含空格 → exact（走最终 return 'exact'）
        # "init.rc" 满足纯符号路径正则
        assert classify_query("init.rc") == "exact"


# ─── 边界情况 ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """空字符串、纯空白等边界输入。"""

    def test_empty_string(self):
        # strip() 后为空，不匹配任何分支，最终返回 exact
        assert classify_query("") == "exact"

    def test_whitespace_only(self):
        # strip() 后为空，同上
        assert classify_query("   ") == "exact"

    def test_leading_trailing_whitespace(self):
        # 前后有空格但内容是 exact 符号
        assert classify_query("  SystemServer  ") == "exact"
