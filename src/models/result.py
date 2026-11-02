"""Result-side models: SQL execution output and the analyser's conclusion."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .query import IntentType


class QueryResult(BaseModel):
    """一次 SQL 查询的原始产物。"""

    sql: str = ""
    columns: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)
    row_count: int = 0
    elapsed_ms: float = 0.0
    truncated: bool = False

    def as_dicts(self) -> List[Dict[str, Any]]:
        """按列名转成字典列表，方便喂给前端表格。"""
        return [dict(zip(self.columns, row)) for row in self.rows]


class Insight(BaseModel):
    """分析结论。这是给业务看的那一层，不是 SQL。"""

    title: str
    intent: IntentType
    metric: str
    value: Optional[float] = None
    previous: Optional[float] = None
    change_pct: Optional[float] = None
    direction: str = "flat"   # up / down / flat
    severity: str = "info"    # info / warning / critical
    summary: str = ""
    details: List[str] = Field(default_factory=list)
