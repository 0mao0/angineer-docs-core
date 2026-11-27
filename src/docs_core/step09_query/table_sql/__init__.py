"""表内数据查询（table_sql）：单表虚拟视图 + 静态预检（2026-11-14 问表施工）。"""
from docs_core.step09_query.table_sql.guard import TABLE_ALIAS, check_sql
from docs_core.step09_query.table_sql.service import run_table_sql

__all__ = ["TABLE_ALIAS", "check_sql", "run_table_sql"]
