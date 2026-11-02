"""Natural language -> QueryIntent, pure rule engine (no LLM, no network).

设计原则：优先命中确定性的关键词规则，命中不了就返回 UNKNOWN 让上层拒绝，
而不是"猜一个差不多的意图"——分析场景里猜错的代价比查不出更高。
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .models.query import IntentType, Metric, QueryIntent


class QueryParser:
    """把中文问题解析成可翻译成 SQL 的结构化意图。"""

    PRODUCTS: Tuple[str, ...] = ("智能手表", "蓝牙耳机", "运动手环")

    # 指标关键词。顺序敏感：转化率必须先于"销量"判断，避免"转化销量"这类表述误判。
    METRIC_KEYWORDS: Tuple[Tuple[Metric, Tuple[str, ...]], ...] = (
        (Metric.CONVERSION_RATE, ("转化率", "转化", "cvr")),
        (Metric.UNITS_SOLD, ("销量", "件数", "卖出", "卖了多少")),
        (Metric.VISITORS, ("访客", "流量", "访问量", "uv")),
        (Metric.REVENUE, ("销售额", "营收", "收入", "gmv", "成交额")),
    )

    # 意图关键词。顺序即优先级：异常 > 对比 > 排名 > 趋势 > 汇总
    INTENT_KEYWORDS: Tuple[Tuple[IntentType, Tuple[str, ...]], ...] = (
        (IntentType.ANOMALY, ("异常", "骤降", "暴跌", "暴涨", "波动")),
        (IntentType.COMPARISON, ("环比", "同比", "对比", "变化")),
        (IntentType.RANKING, ("最高", "最多", "排名", "排行", "top", "哪个产品")),
        (IntentType.TREND, ("趋势", "走势", "逐月")),
        (IntentType.AGGREGATE, ("总额", "总销售额", "合计", "一共", "累计", "总共")),
    )

    def parse(self, question: str) -> QueryIntent:
        """解析一个问题。空串或无法识别时返回 intent=UNKNOWN。"""
        raw = (question or "").strip()
        if not raw:
            return QueryIntent(raw=raw, intent=IntentType.UNKNOWN)

        normalized = raw.lower()
        intent = self._detect_intent(normalized)
        metric = self._detect_metric(normalized)
        filters = self._extract_filters(raw)

        if intent is IntentType.UNKNOWN:
            dimension = None
        elif intent is IntentType.RANKING:
            dimension = "product"
        else:
            dimension = "month"

        return QueryIntent(
            raw=raw,
            intent=intent,
            metric=metric,
            dimension=dimension,
            filters=filters,
            limit=self._extract_limit(normalized, intent),
        )

    # ---------------------------------------------------------------- internal

    def _detect_intent(self, text: str) -> IntentType:
        for intent, keywords in self.INTENT_KEYWORDS:
            if any(kw in text for kw in keywords):
                return intent
        return IntentType.UNKNOWN

    def _detect_metric(self, text: str) -> Metric:
        for metric, keywords in self.METRIC_KEYWORDS:
            if any(kw in text for kw in keywords):
                return metric
        return Metric.REVENUE  # 未指明指标时，默认看销售额

    def _extract_filters(self, text: str) -> Dict[str, object]:
        filters: Dict[str, object] = {}
        for product in self.PRODUCTS:
            if product in text:
                filters["product"] = product
                break

        months = re.search(r"近\s*(\d+)\s*个?月", text)
        if months:
            filters["months"] = int(months.group(1))
        elif "近半年" in text:
            filters["months"] = 6

        return filters

    def _extract_limit(self, text: str, intent: IntentType) -> int:
        months = re.search(r"近\s*(\d+)\s*个?月", text)
        if months:
            return max(1, min(int(months.group(1)), 24))
        if "近半年" in text:
            return 6
        if intent is IntentType.COMPARISON:
            return 2
        if intent is IntentType.ANOMALY:
            return 12
        if intent is IntentType.TREND:
            return 24
        return 10
