"""table_sql（问表）单测：guard 预检 + 单表虚拟视图执行（2026-11-14）。

数据面用 tmp 库文件 + KNOWLEDGE_BASE_DIR 隔离（resolve_* 每次调用现读 env）。
"""
import json
import sqlite3

import pytest

from docs_core.step09_query.table_sql import check_sql, run_table_sql

_CANONICAL_TABLES_DDL = """
CREATE TABLE canonical_tables (
    table_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    page_start INTEGER NOT NULL DEFAULT 0,
    page_end INTEGER NOT NULL DEFAULT 0,
    title TEXT,
    caption TEXT,
    header_rows_json TEXT,
    body_rows_json TEXT
)
"""


def _make_kb(tmp_path):
    db = tmp_path / "knowledge_index.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute(_CANONICAL_TABLES_DDL)
    conn.execute(
        "INSERT INTO canonical_tables (table_id, doc_id, page_start, title,"
        " header_rows_json, body_rows_json) VALUES (?,?,?,?,?,?)",
        (
            "tbl_cover", "doc_a", 3, "混凝土保护层厚度",
            json.dumps([["强度等级", "保护层厚度(mm)"]], ensure_ascii=False),
            json.dumps([["C30", "30"], ["C40", "25"], ["C50", "20"]], ensure_ascii=False),
        ),
    )
    conn.execute(
        "INSERT INTO canonical_tables (table_id, doc_id, header_rows_json, body_rows_json)"
        " VALUES (?,?,?,?)",
        (
            "tbl_noheader", "doc_b",
            json.dumps([]),
            json.dumps([["项目", "数值"], ["氯离子含量", "0.12%"], ["含水率", "3.5%"]], ensure_ascii=False),
        ),
    )
    conn.execute(
        "INSERT INTO canonical_tables (table_id, doc_id, header_rows_json, body_rows_json)"
        " VALUES (?,?,?,?)",
        (
            "tbl_dup", "doc_c",
            json.dumps([["名称", "名称"]], ensure_ascii=False),
            json.dumps([["砂", "1"], ["石", "2"]], ensure_ascii=False),
        ),
    )
    conn.execute(
        "INSERT INTO canonical_tables (table_id, doc_id, header_rows_json, body_rows_json)"
        " VALUES (?,?,?,?)",
        ("tbl_headeronly", "doc_d", json.dumps([["列A"]]), json.dumps([])),
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def kb(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    _make_kb(tmp_path)
    return tmp_path


# ---------------- guard 静态预检 ----------------


def test_guard_rejects_semicolon():
    verdict = check_sql("SELECT 1 FROM t; SELECT 2 FROM t", 100)
    assert verdict["ok"] is False
    assert verdict["error_code"] == "multiple_statements"


def test_guard_allows_single_trailing_semicolon():
    verdict = check_sql("SELECT * FROM t;", 100)
    assert verdict["ok"] is True
    assert "LIMIT 101" in verdict["sql"]  # max+1：让 service 观测截断


def test_guard_rejects_write_keyword():
    assert check_sql("UPDATE t SET x = 1", 100)["error_code"] == "only_select_supported"
    assert check_sql(
        "SELECT 1 FROM t; PRAGMA database_list", 100
    )["error_code"] == "multiple_statements"
    verdict = check_sql("WITH x AS (SELECT 1) DELETE FROM t", 100)
    assert verdict["ok"] is False and verdict["error_code"] == "forbidden_keyword"


def test_guard_rejects_attach_and_other_table():
    verdict = check_sql("SELECT * FROM canonical_tables", 100)
    assert verdict["ok"] is False and verdict["error_code"] == "table_not_allowed"
    # ATTACH 在词法层即拦（能把 canonical 库挂进内存连接，必禁）
    verdict = check_sql("SELECT ATTACH FROM t", 100)
    assert verdict["ok"] is False and verdict["error_code"] == "forbidden_keyword"


def test_guard_injects_limit_keeps_existing():
    verdict = check_sql("SELECT * FROM t LIMIT 5", 100)
    assert verdict["ok"] is True and verdict["sql"].count("LIMIT") == 1


# ---------------- service：schema 卡片 ----------------


def test_schema_card_when_sql_empty(kb):
    result = run_table_sql("tbl_cover")
    assert result["ok"] is True and result["mode"] == "schema"
    names = [column["name"] for column in result["columns"]]
    assert names == ["强度等级", "保护层厚度mm"]  # 括号消毒
    types = {column["name"]: column["type"] for column in result["columns"]}
    assert types["保护层厚度mm"] == "REAL" and types["强度等级"] == "TEXT"


def test_schema_card_percent_column_numeric(kb):
    result = run_table_sql("tbl_noheader")  # 无表头入库：首行提列名
    assert [column["name"] for column in result["columns"]] == ["项目", "数值"]
    types = {column["name"]: column["type"] for column in result["columns"]}
    assert types["数值"] == "REAL"  # '0.12%' 千分位/百分号容忍后可数值化


# ---------------- service：查询执行 ----------------


def test_select_returns_rows_with_row_no(kb):
    result = run_table_sql("tbl_cover", "SELECT 保护层厚度mm FROM t WHERE 强度等级 = 'C40'")
    assert result["ok"] is True and result["mode"] == "result"
    # 投影只含所选列（SQL 语义）；序号仅 SELECT * 时出现
    assert result["rows"] == [{"保护层厚度mm": 25.0}]
    full = run_table_sql("tbl_cover", "SELECT * FROM t WHERE 强度等级 = 'C40'")
    assert full["rows"] == [{"序号": 2, "强度等级": "C40", "保护层厚度mm": 25.0}]


def test_aggregate_on_real_column(kb):
    result = run_table_sql("tbl_cover", "SELECT AVG(保护层厚度mm) AS 均值 FROM t")
    assert result["ok"] is True
    assert abs(result["rows"][0]["均值"] - 25.0) < 1e-9


def test_unknown_column_error_lists_columns(kb):
    result = run_table_sql("tbl_cover", "SELECT 不存在的列 FROM t")
    assert result["ok"] is False and result["error_code"] == "unknown_column"
    assert "保护层厚度mm" in result["hint"]


def test_truncated_at_max_rows(kb):
    result = run_table_sql("tbl_cover", "SELECT * FROM t", max_rows=2)
    assert result["truncated"] is True and result["row_count"] == 2


def test_duplicate_headers_deduped(kb):
    result = run_table_sql("tbl_dup", "SELECT 名称_2 FROM t WHERE 名称 = '石'")
    assert result["ok"] is True
    assert result["rows"] == [{"名称_2": 2.0}]  # 全列可解析 → REAL


def test_empty_table_and_missing_table(kb):
    assert run_table_sql("tbl_headeronly", "SELECT 列A FROM t")["error_code"] == "empty_table"
    assert run_table_sql("tbl_missing")["error_code"] == "table_not_found"
    assert run_table_sql("")["error_code"] == "missing_table_id"


def test_memory_db_physically_isolated(kb):
    # canonical 表根本不存在于内存连接——即便 guard 被绕过，SQL 也摸不到源库
    result = run_table_sql("tbl_cover", "SELECT * FROM sqlite_master WHERE 1=1")
    assert result["ok"] is False and result["error_code"] == "table_not_allowed"


def test_scan_finds_group_file_table(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    _make_kb(tmp_path)
    groups = tmp_path / "groups"
    groups.mkdir()
    conn = sqlite3.connect(str(groups / "standards.sqlite"))
    conn.execute(_CANONICAL_TABLES_DDL)
    conn.execute(
        "INSERT INTO canonical_tables (table_id, doc_id, header_rows_json, body_rows_json)"
        " VALUES (?,?,?,?)",
        (
            "tbl_group", "doc_g",
            json.dumps([["参数"]], ensure_ascii=False),
            json.dumps([["值1"]], ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()
    result = run_table_sql("tbl_group")  # library_id 缺省 → 扫 groups/*.sqlite
    assert result["ok"] is True and result["mode"] == "schema"
    # 未注册库显式路由 → 回退默认单文件（library_registry 契约）
    assert run_table_sql("tbl_group", library_id="lib-not-registered")["error_code"] == "table_not_found"
