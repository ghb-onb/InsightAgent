"""Query-side models: what the user asked, and how it is constrained."""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    """分析意图。规则解析器只会产出这几类之一。"""

    RANKING = "ranking"        # 谁最高 / 排名
    TREND = "trend"            # 时间趋势
    COMPARISON = "comparison"  # 环比 / 同比
    AGGREGATE = "aggregate"    # 总量
    ANOMALY = "anomaly"        # 异常波动
    UNKNOWN = "unknown"


class Metric(str, Enum):
    """可分析指标。每个指标在 translator 里有确定的聚合方式。"""

    REVENUE = "revenue"
    UNITS_SOLD = "units_sold"
    VISITORS = "visitors"
    CONVERSION_RATE = "conversion_rate"


class QueryIntent(BaseModel):
    """自然语言解析出的结构化意图。"""

    raw: str
    intent: IntentType = IntentType.UNKNOWN
    metric: Metric = Metric.REVENUE
    dimension: Optional[str] = None
    filters: Dict[str, Any] = Field(default_factory=dict)
    limit: int = 10
