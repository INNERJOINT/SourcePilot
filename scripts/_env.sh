#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  共享 .env 加载器 — 被所有 run_*.sh 脚本 source 引用
#
#  从项目根目录加载 .env 文件（如果存在）。
#  仅设置当前环境中 *尚未定义* 的变量，
#  因此命令行传入的环境变量始终优先。
#
#  支持的 .env 语法：
#    KEY=VALUE
#    export KEY=VALUE
#    # 注释行
#    KEY="quoted value"
#    KEY='quoted value'
#    KEY=value  # 行内注释
#
#  不支持：
#    多行值、变量插值（$VAR）、转义序列
# ──────────────────────────────────────────────────────

_PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -f "$_PROJ_ROOT/.env" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        # 跳过空行和注释行
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue

        # 去除 export 前缀
        line="${line#export }"
        line="${line#export	}"

        # 分割 key=value（仅在第一个 = 处分割）
        key="${line%%=*}"
        value="${line#*=}"

        # 去除 key 两端空白
        key="${key#"${key%%[![:space:]]*}"}"
        key="${key%"${key##*[![:space:]]}"}"

        # 跳过无效的 key
        [[ -z "$key" || "$key" =~ [^a-zA-Z0-9_] ]] && continue

        # 去除 value 的行内注释（仅对非引号值生效）
        case "$value" in
            \"*\"|\'*\')
                # 引号值：去除首尾引号
                value="${value:1:${#value}-2}"
                ;;
            *)
                # 非引号值：去除行内注释（ # 之后的内容）
                value="${value%%[[:space:]]#*}"
                # 去除尾部空白
                value="${value%"${value##*[![:space:]]}"}"
                ;;
        esac

        # 仅设置当前环境中未定义的变量
        if [ -z "${!key+x}" ]; then
            export "$key=$value"
        fi
    done < "$_PROJ_ROOT/.env"
    echo "Loaded config from $_PROJ_ROOT/.env" >&2
fi
