"""Natural language -> QueryIntent, pure rule engine (no LLM, no network).

设计原则：优先命中确定性的关键词规则，命中不了就返回 UNKNOWN 让上层拒绝，
而不是"猜一个差不多的意图"——分析场景里猜错的代价比查不出更高。
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

from .models.query import IntentType, Metric, QueryIntent


class MetricUnavailableError(ValueError):
    """问的指标在这份数据里没有对应字段。"""


class QueryParser:
    """把中文问题解析成可翻译成 SQL 的结构化意图。

    products / available_metrics 在载入数据后由 InsightAgent 注入：
    问"哪个产品最高"查的是你数据里的产品，而不是写死的 demo 名单。
    没注入时退回内置默认值，保证 parser 可以独立使用。
    """

    PRODUCTS: Tuple[str, ...] = ("智能手表", "蓝牙耳机", "运动手环")

    METRIC_LABEL_CN = {
        Metric.REVENUE: "销售额",
        Metric.UNITS_SOLD: "销量",
        Metric.VISITORS: "访客数",
        Metric.CONVERSION_RATE: "转化率",
    }

    def __init__(
        self,
        products: Optional[Iterable[str]] = None,
        available_metrics: Optional[Iterable[Metric]] = None,
    ):
        self.products: Tuple[str, ...] = tuple(products) if products else self.PRODUCTS
        self.available_metrics: Optional[frozenset] = (
            frozenset(available_metrics) if available_metrics else None
        )

    def update_schema(
        self,
        products: Optional[Iterable[str]] = None,
        metrics: Optional[Iterable[Metric]] = None,
    ) -> "QueryParser":
        """按数据实际内容刷新可识别的产品名与可用指标。"""
        if products is not None:
            cleaned = tuple(str(p).strip() for p in products if str(p).strip())
            if cleaned:
                self.products = cleaned
        if metrics is not None:
            self.available_metrics = frozenset(metrics)
        return self

    def known_products(self) -> Tuple[str, ...]:
        return self.products

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
        blocked: Optional[str] = None
        for metric, keywords in self.METRIC_KEYWORDS:
            hit = next((kw for kw in keywords if kw in text), None)
            if hit is None:
                continue
            if self.available_metrics is not None and metric not in self.available_metrics:
                # 这个词命中了一个这份数据没有的指标：先记住，看后面有没有可用的
                blocked = blocked or hit
                continue
            return metric

        if blocked is not None:
            available = sorted(self.available_metrics or (), key=lambda m: m.value)
            names = "、".join(self.METRIC_LABEL_CN.get(m, m.value) for m in available)
            raise MetricUnavailableError(
                f"这份数据里没有「{blocked}」对应的字段，现在能分析的是：{names}。"
            )
        return self._default_metric()

    def _default_metric(self) -> Metric:
        """没指明指标时的默认值：优先销售额，没有就用剩下的第一个。"""
        if self.available_metrics is None or Metric.REVENUE in self.available_metrics:
            return Metric.REVENUE
        return sorted(self.available_metrics, key=lambda m: m.value)[0]

    def _extract_filters(self, text: str) -> Dict[str, object]:
        filters: Dict[str, object] = {}
        # 长名字优先，避免"华为"抢走"华为GT5"
        for product in sorted(self.products, key=len, reverse=True):
            if product and product in text:
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
