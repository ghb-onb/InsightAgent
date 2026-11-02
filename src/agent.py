"""InsightAgent 编排层：解析 -> 翻译 -> 安全执行 -> 分析，四步一条链。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Union

from .analyzer import InsightAnalyzer
from .executor import SafeQueryExecutor
from .loader import build_database
from .models.query import QueryIntent
from .models.result import QueryResult
from .parser import QueryParser
from .translator import SQLTranslator


class InsightAgent:
    """用一句中文问题换一份可执行的分析结论。"""

    def __init__(
        self,
        db_path: Union[str, Path] = "insight.db",
        dataset_path: Optional[Union[str, Path]] = None,
        max_rows: int = 200,
    ):
        self.db_path = str(db_path)
        self.parser = QueryParser()
        self.translator = SQLTranslator()
        self.executor = SafeQueryExecutor(self.db_path, max_rows=max_rows)
        self.analyzer = InsightAnalyzer()

        if dataset_path is not None:
            self.load(dataset_path)

    # ------------------------------------------------------------------ setup

    def load(self, dataset_path: Union[str, Path]) -> int:
        """载入 CSV/Excel 并重建分析库，返回入库行数。"""
        return build_database(dataset_path, self.db_path)

    # ------------------------------------------------------------------- ask

    def explore(self, question: str) -> Dict[str, Any]:
        """问一句，拿回意图 / SQL / 原始结果 / 结论。"""
        intent: QueryIntent = self.parser.parse(question)
        sql = self.translator.translate(intent)
        result: QueryResult = self.executor.execute(sql)
        insight = self.analyzer.analyze(intent, result)

        return {
            "question": question,
            "intent": intent,
            "sql": result.sql,
            "columns": result.columns,
            "rows": result.rows,
            "row_count": result.row_count,
            "elapsed_ms": result.elapsed_ms,
            "insight": insight,
        }

    __call__ = explore
