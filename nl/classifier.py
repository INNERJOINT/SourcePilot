"""
查询意图分类器

规则优先策略：区分精确查询（符号名、路径、正则）与自然语言查询。
改进点：混合查询（NL 指示词 + 符号名）优先判定为 NL。
"""

import re


def classify_query(query: str) -> str:
    """
    返回 'exact' 或 'natural_language'。
    """
    q = query.strip()

    # Zoekt 修饰符 → 一定是 exact
    if re.match(r'^(sym:|file:|r:|lang:|case:)', q):
        return 'exact'

    # 正则表达式
    if re.match(r'^r".*"$', q):
        return 'exact'

    # NL 指示词 → 优先 NL（即使含有 CamelCase）
    nl_words = [
        '怎么', '什么', '如何', '为什么', '哪里', '哪些', '哪个',
        '流程', '机制', '原理', '影响', '模块', '功能', '逻辑',
        '启动', '调用', '实现', '过程', '步骤', '作用', '区别', '解释',
        '在哪', '怎样', '分析', '介绍', '说明', '包含', '涉及', '相关',
        'how', 'what', 'why', 'where', 'when', 'explain', 'describe', 'find',
    ]
    if any(w in q.lower() for w in nl_words):
        return 'natural_language'

    # 中文 + 代码标识符混合 → NL（如 "ro.seewo.tags有哪些引用"）
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', q))
    has_code = bool(re.search(r'[a-zA-Z_][a-zA-Z0-9_.]{2,}', q))
    if has_chinese and has_code:
        return 'natural_language'

    # 纯符号/路径（无空格）→ exact
    if re.match(r'^[A-Za-z0-9_./:\-]+$', q):
        return 'exact'

    # 较长句子 → NL（中文不一定有空格，用长度判断）
    if len(q) > 15:
        return 'natural_language'

    return 'exact'
