"""table_sql 静态预检（执行前 dry-plan 同款，2026-11-14 问表施工）。

模型生成的 SQL 先过本闸再执行：只许单条 SELECT（或 WITH...SELECT）、
表引用只认内存关系别名 ``t``、写/管控关键字整词黑名单。
列名不在这里做正则白名单（死骨架旧法易误杀）——内存库里本来就只有这一张表，
写错列名由 sqlite「no such column」触发、service 转结构化错误并把可用列回给模型。

返回约定：通过返回净化后的 SQL（补 LIMIT）；不通过返回 {error_code, message}，
hint（可用列清单 + 示例）由 service 侧统一拼装。
"""
import re
from typing import Dict

TABLE_ALIAS = "t"

# 整词黑名单：写操作 + 库管控面（ATTACH 能把 canonical 库挂进内存连接，必禁；
# 词表覆盖旧 sql_validator 黑名单并补 ATTACH/DETACH/PRAGMA/INSTALL/LOAD）
_FORBIDDEN = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "ATTACH", "DETACH",
    "PRAGMA", "VACUUM", "CREATE", "REPLACE", "REINDEX", "TRUNCATE",
    "INSTALL", "LOAD_EXTENSION", "BEGIN", "COMMIT", "ROLLBACK",
    "GRANT", "REVOKE",
)
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(_FORBIDDEN) + r")\b", re.IGNORECASE)

# FROM/JOIN 后的表引用（含子查询入口也先命中 FROM 再被嵌套检查兜住：
# 嵌套里出现的任何非 t 表名都会在集合里现形）
_TABLE_REF_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+([A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*)",
    re.IGNORECASE,
)
_LIMIT_RE = re.compile(r"\bLIMIT\b", re.IGNORECASE)
_START_RE = re.compile(r"^\(?\s*(SELECT|WITH)\b", re.IGNORECASE)


def check_sql(sql: str, max_rows: int) -> Dict[str, object]:
    """预检一条 SQL。通过 → {"ok": True, "sql": 净化后语句}；不过 → {"ok": False, error_code, message}。"""
    text = (sql or "").strip()
    while text.endswith(";"):
        text = text[:-1].strip()
    if not text:
        return {"ok": False, "error_code": "empty_sql", "message": "SQL 为空"}
    if ";" in text:
        return {
            "ok": False,
            "error_code": "multiple_statements",
            "message": "只允许单条语句，SQL 中不能含分号",
        }
    if not _START_RE.match(text):
        return {
            "ok": False,
            "error_code": "only_select_supported",
            "message": "只支持 SELECT 查询（可用 WITH 开头）",
        }
    forbidden = _FORBIDDEN_RE.search(text)
    if forbidden:
        return {
            "ok": False,
            "error_code": "forbidden_keyword",
            "message": f"SQL 含不允许的关键字: {forbidden.group(1)}",
        }
    table_refs = {ref.lower() for ref in _TABLE_REF_RE.findall(text)}
    for ref in table_refs:
        if ref != TABLE_ALIAS:
            return {
                "ok": False,
                "error_code": "table_not_allowed",
                "message": f"表引用 {ref} 不在允许范围，只能查 {TABLE_ALIAS}",
            }
    if not _LIMIT_RE.search(text):
        # +1 行让 service 能观测「还有更多」→ truncated 置真（否则恒判不出截断）
        text = f"{text} LIMIT {int(max(1, max_rows) + 1)}"
    return {"ok": True, "sql": text}
