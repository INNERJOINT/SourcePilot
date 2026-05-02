"""
Query intent classifier

Rule-first strategy: distinguishes exact queries (symbol names, paths, regexes)
from natural-language queries.
Improvement: mixed queries (NL indicator words + symbol names) are classified as NL first.
"""

import re


def classify_query(query: str) -> str:
    """
    Returns 'exact' or 'natural_language'.
    """
    q = query.strip()

    # Zoekt modifiers → always exact
    if re.match(r'^(sym:|file:|r:|lang:|case:)', q):
        return 'exact'

    # Regular expressions
    if re.match(r'^r".*"$', q):
        return 'exact'

    # NL indicator words → prefer NL (even if CamelCase is present)
    nl_words = [
        '怎么', '什么', '如何', '为什么', '哪里', '哪些', '哪个',
        '流程', '机制', '原理', '影响', '模块', '功能', '逻辑',
        '启动', '调用', '实现', '过程', '步骤', '作用', '区别', '解释',
        '在哪', '怎样', '分析', '介绍', '说明', '包含', '涉及', '相关',
        'how', 'what', 'why', 'where', 'when', 'explain', 'describe', 'find',
    ]
    if any(w in q.lower() for w in nl_words):
        return 'natural_language'

    # Mixed Chinese + code identifier → NL (e.g. "what references ro.vendor.tags")
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', q))
    has_code = bool(re.search(r'[a-zA-Z_][a-zA-Z0-9_.]{2,}', q))
    if has_chinese and has_code:
        return 'natural_language'

    # Pure symbol/path (no spaces) → exact
    if re.match(r'^[A-Za-z0-9_./:\-]+$', q):
        return 'exact'

    # Long sentence → NL (Chinese text may have no spaces, so use length heuristic)
    if len(q) > 15:
        return 'natural_language'

    return 'exact'
