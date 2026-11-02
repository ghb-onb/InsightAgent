"""InsightAgent 编排层：解析 -> 翻译 -> 安全执行 -> 分析，四步一条链。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Union

from .analyzer import InsightAnalyzer
from .executor import SafeQueryExecutor
from .loader import clean_dataset, map_columns, read_dataset, write_frame
from .models.query import Metric, QueryIntent
from .models.result import QueryResult
from .parser import QueryParser
from .translator import SQLTranslator

# 数据列 -> 可问的指标。列不在就当作这个指标不能问。
METRIC_BY_COLUMN = {
    "revenue": Metric.REVENUE,
    "units_sold": Metric.UNITS_SOLD,
    "visitors": Metric.VISITORS,
    "conversion_rate": Metric.CONVERSION_RATE,
}


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
        self.schema: Dict[str, Any] = {
            "products": [], "metrics": [], "columns": [],
            "mapping": {}, "dimension_label": "产品", "rows": 0,
        }

        if dataset_path is not None:
            self.load(dataset_path)

    # ------------------------------------------------------------------ setup

    def load(self, dataset_path: Union[str, Path]) -> int:
        """载入 CSV/Excel、重建分析库，并把数据里的真实字段交给 parser。"""
        raw = read_dataset(dataset_path)
        mapping = map_columns(raw.columns)
        frame = clean_dataset(raw)
        rows = write_frame(frame, self.db_path)
        self._sync_schema(frame, mapping)
        return rows

    def _sync_schema(self, frame, mapping: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """按数据实际内容刷新 parser：产品名、可用指标、维度叫法。"""
        products = []
        if "product" in frame.columns:
            products = [
                str(value) for value in frame["product"].dropna().unique() if str(value).strip()
            ]
            products.sort()

        metrics = [
            metric
            for column, metric in METRIC_BY_COLUMN.items()
            if column in frame.columns and frame[column].notna().any()
        ]

        # product 列在原始表里叫什么（店铺/门店/商品/产品），示例问题要用这个词。
        # 原列名本身就叫 product 时没有信息量，退回"产品"。
        dimension_label = "产品"
        for source_column, canonical in (mapping or {}).items():
            if canonical == "product":
                label = str(source_column).strip()
                if label and label.lower() != "product":
                    dimension_label = label
                break

        self.parser.update_schema(products=products, metrics=metrics)
        self.schema = {
            "products": products,
            "metrics": [metric.value for metric in metrics],
            "columns": [str(column) for column in frame.columns],
            "mapping": dict(mapping or {}),
            "dimension_label": dimension_label,
            "rows": int(len(frame)),
        }
        return self.schema

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
