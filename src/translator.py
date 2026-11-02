"""QueryIntent -> SQL. 只生成 SELECT，且表名和列名都是代码里写死的，不接受外部拼接。"""
from __future__ import annotations

from typing import List

from .models.query import IntentType, Metric, QueryIntent


class UnsupportedIntentError(ValueError):
    """意图无法翻译成 SQL（通常是 UNKNOWN）。"""


class SQLTranslator:
    """规则式 NL->SQL。模板固定、参数白名单，杜绝字符串拼接注入。"""

    TABLE = "sales"

    # 每个指标的聚合方式。转化率是率值，必须用 AVG 而不是 SUM。
    METRIC_SQL = {
        Metric.REVENUE: "SUM(revenue)",
        Metric.UNITS_SOLD: "SUM(units_sold)",
        Metric.VISITORS: "SUM(visitors)",
        Metric.CONVERSION_RATE: "AVG(conversion_rate)",
    }

    METRIC_LABEL = {
        Metric.REVENUE: "销售额",
        Metric.UNITS_SOLD: "销量",
        Metric.VISITORS: "访客数",
        Metric.CONVERSION_RATE: "转化率",
    }

    def translate(self, intent: QueryIntent) -> str:
        """把一个意图翻译成一条 SQL 字符串。"""
        if intent.intent is IntentType.UNKNOWN:
            raise UnsupportedIntentError(f"无法理解的问题：{intent.raw!r}")

        if intent.intent is IntentType.RANKING:
            return self._ranking_sql(intent)
        if intent.intent is IntentType.AGGREGATE:
            return self._aggregate_sql(intent)
        if intent.intent is IntentType.COMPARISON:
            return self._timeline_sql(intent, limit=2, descending=True)
        if intent.intent is IntentType.ANOMALY:
            return self._timeline_sql(intent, limit=12, descending=True)
        return self._timeline_sql(intent, limit=intent.limit, descending=True)

    # ---------------------------------------------------------------- queries

    def _ranking_sql(self, intent: QueryIntent) -> str:
        return (
            f"SELECT product AS dimension, {self._agg(intent)} AS metric_value\n"
            f"FROM {self.TABLE}\n"
            f"{self._where(intent)}"
            f"GROUP BY product\n"
            f"ORDER BY metric_value DESC\n"
            f"LIMIT {int(intent.limit)}"
        )

    def _timeline_sql(self, intent: QueryIntent, limit: int, descending: bool = False) -> str:
        """时间序列查询。

        descending=True 表示"取最近 N 期"：先按时间倒序 LIMIT，再在外层按时间
        正序返回。这样调用方拿到的永远是升序序列（可直接画图），而 LIMIT 截取的
        是**最近** N 期而不是最早 N 期。
        """
        order = "DESC" if descending else "ASC"
        core = (
            f"SELECT month AS dimension, {self._agg(intent)} AS metric_value\n"
            f"FROM {self.TABLE}\n"
            f"{self._where(intent)}"
            f"GROUP BY month\n"
            f"ORDER BY month {order}\n"
            f"LIMIT {int(limit)}"
        )
        if descending:
            return (
                f"SELECT dimension, metric_value FROM (\n{core}\n)\n"
                f"ORDER BY dimension ASC"
            )
        return core

    def _aggregate_sql(self, intent: QueryIntent) -> str:
        return (
            f"SELECT 'ALL' AS dimension, {self._agg(intent)} AS metric_value\n"
            f"FROM {self.TABLE}\n"
            f"{self._where(intent)}"
            f"LIMIT 1"
        )

    # ---------------------------------------------------------------- helpers

    def _agg(self, intent: QueryIntent) -> str:
        return self.METRIC_SQL[intent.metric]

    def _where(self, intent: QueryIntent) -> str:
        clauses: List[str] = []
        product = intent.filters.get("product")
        if product:
            # 单引号转义：产品名来自固定白名单，这里仍做一次转义以防未来放开
            safe = str(product).replace("'", "''")
            clauses.append(f"product = '{safe}'")
        month_from = intent.filters.get("month_from")
        if month_from:
            safe_month = str(month_from).replace("'", "''")
            clauses.append(f"month >= '{safe_month}'")
        return f"WHERE {' AND '.join(clauses)}\n" if clauses else ""
