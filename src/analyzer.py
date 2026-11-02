"""把查询结果翻译成业务结论：排名、环比变化、异常判定。"""
from __future__ import annotations

from typing import List, Optional, Tuple

from .models.query import IntentType, Metric, QueryIntent
from .models.result import Insight, QueryResult
from .translator import SQLTranslator


class InsightAnalyzer:
    """结果分析。只吃 QueryResult，不碰数据库。"""

    # 环比波动超过这个百分比就标记为异常
    ANOMALY_THRESHOLD = 30.0
    WARNING_THRESHOLD = 10.0

    def analyze(self, intent: QueryIntent, result: QueryResult) -> Insight:
        if not result.rows:
            return Insight(
                title="没有查到数据",
                intent=intent.intent,
                metric=intent.metric.value,
                summary=f"问题「{intent.raw}」没有命中任何数据，请检查筛选条件。",
            )

        if intent.intent is IntentType.RANKING:
            return self._ranking(intent, result)
        if intent.intent is IntentType.AGGREGATE:
            return self._aggregate(intent, result)
        return self._change(intent, result)

    # ---------------------------------------------------------------- ranking

    def _ranking(self, intent: QueryIntent, result: QueryResult) -> Insight:
        dimension, value = result.rows[0]
        label = SQLTranslator.METRIC_LABEL[intent.metric]
        others = "、".join(str(r[0]) for r in result.rows[1:4])

        return Insight(
            title=f"{dimension} {label}最高",
            intent=intent.intent,
            metric=intent.metric.value,
            value=float(value),
            summary=(
                f"按{label}排名，{dimension}以 {self._fmt(intent.metric, value)} 居首"
                + (f"，其后是 {others}。" if others else "。")
            ),
            details=[f"{r[0]}: {self._fmt(intent.metric, r[1])}" for r in result.rows],
        )

    # -------------------------------------------------------------- aggregate

    def _aggregate(self, intent: QueryIntent, result: QueryResult) -> Insight:
        value = result.rows[0][1]
        label = SQLTranslator.METRIC_LABEL[intent.metric]
        return Insight(
            title=f"合计{label}",
            intent=intent.intent,
            metric=intent.metric.value,
            value=float(value),
            summary=f"筛选范围内{label}合计为 {self._fmt(intent.metric, value)}。",
        )

    # ----------------------------------------------------------------- change

    def _change(self, intent: QueryIntent, result: QueryResult) -> Insight:
        series: List[Tuple[str, float]] = sorted(
            ((str(r[0]), float(r[1])) for r in result.rows), key=lambda item: item[0]
        )
        if len(series) < 2:
            label, value = series[-1]
            return Insight(
                title=f"{label} {SQLTranslator.METRIC_LABEL[intent.metric]}",
                intent=intent.intent,
                metric=intent.metric.value,
                value=value,
                summary="只有一个数据点，无法计算环比。",
            )

        (prev_label, prev_value), (last_label, last_value) = series[-2], series[-1]
        change_pct = self._pct_change(prev_value, last_value)
        direction = self._direction(change_pct)
        severity = self._severity(intent, change_pct)

        label = SQLTranslator.METRIC_LABEL[intent.metric]
        arrow = {"up": "上升", "down": "下降", "flat": "基本持平"}[direction]
        change_text = f"{abs(change_pct):.1f}%" if change_pct is not None else "未知"

        details = [f"{dim}: {self._fmt(intent.metric, val)}" for dim, val in series[-6:]]

        insight = Insight(
            title=f"{label}环比{arrow} {change_text}",
            intent=intent.intent,
            metric=intent.metric.value,
            value=last_value,
            previous=prev_value,
            change_pct=change_pct,
            direction=direction,
            severity=severity,
            summary=(
                f"{last_label} 的{label}为 {self._fmt(intent.metric, last_value)}，"
                f"相比 {prev_label} 的 {self._fmt(intent.metric, prev_value)} "
                f"{arrow} {change_text}。"
            ),
            details=details,
        )

        if severity == "critical":
            insight.details.insert(0, "⚠ 波动超过 30% 阈值，建议排查活动结束、断货或埋点异常。")

        return insight

    # ----------------------------------------------------------------- utils

    @staticmethod
    def _pct_change(previous: float, current: float) -> Optional[float]:
        if not previous:
            return None
        return round((current - previous) / abs(previous) * 100, 1)

    @staticmethod
    def _direction(change_pct: Optional[float]) -> str:
        if change_pct is None or abs(change_pct) < 0.05:
            return "flat"
        return "up" if change_pct > 0 else "down"

    def _severity(self, intent: QueryIntent, change_pct: Optional[float]) -> str:
        if change_pct is None:
            return "info"
        magnitude = abs(change_pct)
        if magnitude >= self.ANOMALY_THRESHOLD:
            return "critical"
        if intent.intent is IntentType.ANOMALY or magnitude >= self.WARNING_THRESHOLD:
            return "warning"
        return "info"

    @staticmethod
    def _fmt(metric: Metric, value: float) -> str:
        if metric is Metric.CONVERSION_RATE:
            return f"{value:.2f}%"
        if metric is Metric.REVENUE:
            return f"¥{value:,.0f}"
        return f"{value:,.0f}"
