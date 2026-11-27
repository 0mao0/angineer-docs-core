"""表内数据查询（table_sql）：单表虚拟视图（2026-11-14 问表施工，Wren 思路对照）。

链路：table_search 定位表（模型由此看到表头与行值＝schema 卡片）→ 本服务把该表
``canonical_tables.header_rows_json / body_rows_json`` 灌进 ``:memory:`` sqlite
的**单关系**（固定别名 ``t``）→ 执行模型写的单表 SELECT（guard 预检 + 只读 +
行数上限 + 超时中断）。内存库里物理上只有这一张表，白名单只是第二层护栏。

失败一律返回结构化错误 ``{ok: False, error_code, message, hint}``（工具语义、
不抛异常）；hint 列出全部可用列名与示例——报错即自纠引导（dry-plan 对照结论）。

``sql`` 传空＝先取 schema 卡片（列名/类型/样例值），工具提示词按「先取卡片再写
SQL」引导，避免模型照 table_search 文本猜标识符。
"""
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docs_core.library_registry import resolve_index_db_path
from docs_core.paths import resolve_knowledge_base_dir, resolve_knowledge_index_db_path

from .guard import TABLE_ALIAS, check_sql

DEFAULT_MAX_ROWS = 100
DEFAULT_TIMEOUT_S = 3.0
ROW_NO_COLUMN = "序号"
_SCHEMA_SAMPLE_LIMIT = 3

# 消毒：SQLite 双引号标识符容 CJK，但引号/分号/括号/空白会破坏解析或留注入面，一律去掉
_UNSAFE_IDENT_RE = re.compile(r"[\"'`\s;()（）\[\]]+")


def _error(error_code: str, message: str, hint: str = "") -> Dict[str, Any]:
    payload: Dict[str, Any] = {"ok": False, "error_code": error_code, "message": message}
    if hint:
        payload["hint"] = hint
    return payload


def _candidate_db_paths(library_id: Optional[str]) -> List[Path]:
    """按库路由；未给库时扫默认单文件 + groups/*.sqlite（死骨架旧口径只连单文件，已修）。"""
    paths: List[Path] = []
    if library_id:
        paths.append(resolve_index_db_path(library_id))
    else:
        paths.append(resolve_knowledge_index_db_path())
        groups_dir = resolve_knowledge_base_dir() / "groups"
        if groups_dir.is_dir():
            paths.extend(sorted(groups_dir.glob("*.sqlite")))
    uniq: List[Path] = []
    for path in paths:
        if path not in uniq:
            uniq.append(path)
    return uniq


def _open_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _load_table_row(table_id: str, library_id: Optional[str]) -> Optional[Dict[str, Any]]:
    for path in _candidate_db_paths(library_id):
        if not path.exists():
            continue
        try:
            conn = _open_ro(path)
        except sqlite3.Error:
            continue
        try:
            row = conn.execute(
                "SELECT header_rows_json, body_rows_json, title, caption, page_start, doc_id"
                " FROM canonical_tables WHERE table_id = ?",
                (table_id,),
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
        if row is not None:
            return dict(row)
    return None


# 逐字复制自 step04_structure/shared/table_semantics.py（normalize_table_cell /
# build_table_schema）：query 层禁止 import 摄取生产模块（solo_fallback 契约守卫），
# 两函数为无状态纯函数，语义以那边为准，改动须两处同步。
def _normalize_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _merge_header_schema(headers: List[List[str]]) -> List[str]:
    ncols = max((len(row) for row in headers), default=0)
    schema: List[str] = []
    for col in range(ncols):
        parts: List[str] = []
        prev: Optional[str] = None
        for row in headers:
            cell = _normalize_cell(row[col]) if col < len(row) else ""
            if cell and cell != prev:
                parts.append(cell)
            if cell:
                prev = cell
        schema.append(" ".join(parts))
    return schema


def _load_json_rows(raw: Any) -> List[List[str]]:
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [
        [_normalize_cell(cell) for cell in row]
        for row in data
        if isinstance(row, list)
    ]


def _coerce_number(cell: str) -> Tuple[Optional[float], bool]:
    """单元格数值化（千分位逗号/百分号容忍）；返回 (值, 可解析)。空串视为可解析 NULL。"""
    text = (cell or "").strip().replace(",", "").replace("，", "")
    if text.endswith("%"):
        text = text[:-1]
    if not text:
        return None, True
    try:
        return float(text), True
    except ValueError:
        return None, False


def _build_columns(
    header_rows: List[List[str]], body_rows: List[List[str]]
) -> Tuple[List[str], List[str], int]:
    """列名（消毒+去重）与列类型（全列可数值化 → REAL）。返回 (names, types, ncols)。"""
    schema = _merge_header_schema(header_rows)
    ncols = max([len(row) for row in body_rows] + [len(schema), 0])
    names: List[str] = []
    used: set = set()
    for index in range(ncols):
        base = schema[index].strip() if index < len(schema) and schema[index].strip() else f"列{index + 1}"
        base = _UNSAFE_IDENT_RE.sub("", base) or f"列{index + 1}"
        name = base
        suffix = 2
        while name in used or name == ROW_NO_COLUMN:
            name = f"{base}_{suffix}"
            suffix += 1
        used.add(name)
        names.append(name)

    types: List[str] = []
    for index in range(ncols):
        saw_value = False
        numeric = True
        for row in body_rows:
            cell = row[index] if index < len(row) else ""
            if not cell:
                continue
            saw_value = True
            _, parsed = _coerce_number(cell)
            if not parsed:
                numeric = False
                break
        types.append("REAL" if (numeric and saw_value) else "TEXT")
    return names, types, ncols


def _memory_table(
    names: List[str], types: List[str], body_rows: List[List[str]], ncols: int
) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    columns_sql = ", ".join(
        [f'"{ROW_NO_COLUMN}" INTEGER']
        + [f'"{name}" {sql_type}' for name, sql_type in zip(names, types)]
    )
    conn.execute(f"CREATE TABLE {TABLE_ALIAS} ({columns_sql})")
    rows: List[List[Any]] = []
    for row_no, row in enumerate(body_rows, start=1):
        values: List[Any] = [row_no]
        for index, sql_type in enumerate(types):
            cell = row[index] if index < len(row) else ""
            if sql_type == "REAL":
                value, _ = _coerce_number(cell)
                values.append(value)  # 空/无法解析（不会发生）→ NULL
            else:
                values.append(cell)
        rows.append(values)
    conn.executemany(
        f"INSERT INTO {TABLE_ALIAS} VALUES ({', '.join(['?'] * (ncols + 1))})", rows
    )
    conn.commit()
    return conn


def _schema_card(
    conn: sqlite3.Connection, names: List[str], types: List[str]
) -> List[Dict[str, Any]]:
    card: List[Dict[str, Any]] = []
    for name, sql_type in zip(names, types):
        samples = [
            row[0]
            for row in conn.execute(
                f'SELECT "{name}" FROM {TABLE_ALIAS} WHERE "{name}" IS NOT NULL '
                f"LIMIT {int(_SCHEMA_SAMPLE_LIMIT)}"
            ).fetchall()
        ]
        card.append({"name": name, "type": sql_type, "samples": samples})
    return card


def _columns_hint(names: List[str]) -> str:
    return (
        f"可用列：{'、'.join(names)}；表名固定为 {TABLE_ALIAS}；"
        f"示例：SELECT * FROM {TABLE_ALIAS} WHERE {names[0] if names else '列1'} LIKE '%关键词%' LIMIT 20"
    )


def run_table_sql(
    table_id: str,
    sql: str = "",
    *,
    library_id: Optional[str] = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> Dict[str, Any]:
    """问表主入口。sql 为空＝返回 schema 卡片；否则 guard→内存表→只读执行。"""
    table_id = str(table_id or "").strip()
    if not table_id:
        return _error("missing_table_id", "缺少 table_id", "先用 table_search 定位表，取 metadata.table_id")

    raw = _load_table_row(table_id, library_id)
    if raw is None:
        return _error(
            "table_not_found",
            f"未找到表格 {table_id}",
            "确认 table_id 来自 table_search 返回，且库范围正确（library_id 缺省=当前会话库，\"all\"=全库扫描）",
        )

    header_rows = _load_json_rows(raw.get("header_rows_json"))
    body_rows = _load_json_rows(raw.get("body_rows_json"))
    if not header_rows and body_rows:
        header_rows, body_rows = body_rows[:1], body_rows[1:]  # 无表头入库的表：首行提列名
    if not body_rows:
        return _error("empty_table", "此表没有可查询的数据行", "请用 table_search 直读表文本")

    names, types, ncols = _build_columns(header_rows, body_rows)
    if ncols <= 0:
        return _error("no_columns", "此表无法提取列名", "该表可能是横道图/退化结构，请用 table_search 直读")

    conn = _memory_table(names, types, body_rows, ncols)
    try:
        table_title = str(raw.get("title") or raw.get("caption") or "").strip()
        if not str(sql or "").strip():
            return {
                "ok": True,
                "mode": "schema",
                "table_id": table_id,
                "table_title": table_title,
                "doc_id": raw.get("doc_id") or "",
                "page_start": raw.get("page_start"),
                "row_count": len(body_rows),
                "columns": _schema_card(conn, names, types),
                "hint": f"照上面的列名写单表 SELECT（表名 {TABLE_ALIAS}），再带 sql 参数调用本工具执行",
            }

        verdict = check_sql(sql, max_rows)
        if not verdict.get("ok"):
            error = dict(verdict)
            error["hint"] = _columns_hint(names)
            return error

        final_sql = str(verdict["sql"])
        deadline = time.monotonic() + max(0.5, timeout_s)
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 2000)
        try:
            cursor = conn.execute(final_sql)
        except sqlite3.OperationalError as exc:  # no such column / syntax / interrupted
            text = str(exc)
            if "interrupted" in text.lower():
                return _error("query_timeout", f"查询超过 {timeout_s:.0f} 秒被中止", "请缩短 WHERE 条件或只取必要列")
            column_match = re.search(r"no such column:?\s*([^;]+)", text)
            if column_match:
                return _error(
                    "unknown_column",
                    f"列名不存在: {column_match.group(1).strip()}",
                    _columns_hint(names),
                )
            return _error("sql_error", f"SQL 执行失败: {text}", _columns_hint(names))
        fetched = cursor.fetchmany(max(1, int(max_rows)) + 1)
        truncated = len(fetched) > max_rows
        # 结果列名以 cursor.description 为准（投影/AS 别名列数与建表列不等，硬拼会错位）
        result_columns = [str(desc[0]) for desc in cursor.description]
        rows = [dict(zip(result_columns, row)) for row in fetched[: max(1, int(max_rows))]]
        return {
            "ok": True,
            "mode": "result",
            "table_id": table_id,
            "table_title": table_title,
            "doc_id": raw.get("doc_id") or "",
            "page_start": raw.get("page_start"),
            "columns": result_columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "executed_sql": final_sql,
        }
    finally:
        conn.close()
