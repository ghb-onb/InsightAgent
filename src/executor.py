"""Read-only SQL execution guarded by three independent checks.

1. 语句级：必须是单条 SELECT；
2. 词法级：禁止 DDL/DML 关键字与注释；
3. 对象级：FROM / JOIN 的表必须在白名单内。
另外连接本身用 sqlite 的 `mode=ro` 打开，即使前面三道全被绕过，写入也会被数据库拒绝。
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Set, Union

from .models.result import QueryResult


class UnsafeQueryError(ValueError):
    """SQL 未通过安全校验。"""


class QueryExecutionError(RuntimeError):
    """SQL 通过校验但执行失败（语法错误、字段不存在等）。"""


class SafeQueryExecutor:
    """执行查询，并强制只读、白名单与行数上限。"""

    ALLOWED_TABLES: Set[str] = {"sales"}

    FORBIDDEN_VERBS: Set[str] = {
        "insert", "update", "delete", "drop", "alter", "create", "replace",
        "truncate", "attach", "detach", "pragma", "vacuum", "reindex",
        "transaction", "commit", "rollback", "grant", "revoke",
    }

    def __init__(self, db_path: Union[str, Path], max_rows: int = 200):
        self.db_path = str(db_path)
        self.max_rows = int(max_rows)

    # ---------------------------------------------------------------- guards

    def validate(self, sql: str) -> str:
        """校验并返回规范化后的 SQL（去尾分号）。不通过抛 UnsafeQueryError。"""
        raw = (sql or "").strip()
        if not raw:
            raise UnsafeQueryError("SQL 为空")

        if "--" in raw or "/*" in raw:
            raise UnsafeQueryError("不允许 SQL 注释，注释可用于截断后续校验")

        body = raw.rstrip().rstrip(";").strip()
        if ";" in body:
            raise UnsafeQueryError("不允许多条语句")

        if not re.match(r"^select\b", body, re.IGNORECASE):
            raise UnsafeQueryError("只允许 SELECT 查询")

        tokens = set(re.findall(r"[a-z_]+", body.lower()))
        hit = tokens & self.FORBIDDEN_VERBS
        if hit:
            raise UnsafeQueryError(f"包含被禁止的关键字：{', '.join(sorted(hit))}")

        tables = {
            name.lower()
            for name in re.findall(
                r"\b(?:from|join)\s+([a-zA-Z_][\w]*)", body, re.IGNORECASE
            )
        }
        unknown = tables - self.ALLOWED_TABLES
        if unknown:
            raise UnsafeQueryError(f"表不在白名单内：{', '.join(sorted(unknown))}")

        return body

    # ---------------------------------------------------------------- execute

    def execute(self, sql: str) -> QueryResult:
        """校验后执行，返回 QueryResult。"""
        body = self.validate(sql)

        uri = "file:" + Path(self.db_path).resolve().as_posix() + "?mode=ro"
        started = time.perf_counter()
        try:
            connection = sqlite3.connect(uri, uri=True)
            try:
                cursor = connection.execute(body)
                columns = [d[0] for d in (cursor.description or [])]
                fetched = cursor.fetchmany(self.max_rows + 1)
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise QueryExecutionError(f"SQL 执行失败：{exc}") from exc

        elapsed_ms = (time.perf_counter() - started) * 1000
        truncated = len(fetched) > self.max_rows
        rows = [list(row) for row in fetched[: self.max_rows]]

        return QueryResult(
            sql=body,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            elapsed_ms=round(elapsed_ms, 3),
            truncated=truncated,
        )
