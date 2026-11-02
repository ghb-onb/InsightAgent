"""InsightAgent test suite - 31 tests across parser / translator / executor /
loader / analyzer / visualizer / integration."""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest
from matplotlib.figure import Figure

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import InsightAgent
from src.analyzer import InsightAnalyzer
from src.executor import SafeQueryExecutor, UnsafeQueryError
from src.loader import build_database, clean_dataset, read_dataset
from src.models.query import IntentType, Metric, QueryIntent
from src.models.result import QueryResult
from src.parser import QueryParser
from src.translator import SQLTranslator, UnsupportedIntentError
from src.visualizer import ChartBuilder

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_CSV = os.path.join(BASE_DIR, "demo_data", "sales_data.csv")


# ===== fixtures =====
@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "insight.db"
    build_database(DEMO_CSV, path)
    return str(path)


@pytest.fixture()
def executor(db_path):
    return SafeQueryExecutor(db_path, max_rows=50)


@pytest.fixture()
def agent(db_path):
    return InsightAgent(db_path=db_path)


# ===== Parser tests (6) =====
class TestParser:
    def test_detect_ranking_intent(self):
        intent = QueryParser().parse("哪个产品销售额最高")
        assert intent.intent == IntentType.RANKING
        assert intent.dimension == "product"

    def test_detect_trend_intent(self):
        intent = QueryParser().parse("智能手表销售额趋势")
        assert intent.intent == IntentType.TREND
        assert intent.dimension == "month"

    def test_detect_comparison_intent(self):
        intent = QueryParser().parse("智能手表销售额环比变化")
        assert intent.intent == IntentType.COMPARISON
        assert intent.limit == 2

    def test_detect_metrics(self):
        parser = QueryParser()
        assert parser.parse("哪个产品销售额最高").metric == Metric.REVENUE
        assert parser.parse("智能手表转化率怎么样").metric == Metric.CONVERSION_RATE

    def test_extract_product_filter(self):
        intent = QueryParser().parse("智能手表销售额环比变化")
        assert intent.filters["product"] == "智能手表"

    def test_unknown_intent(self):
        intent = QueryParser().parse("你好呀")
        assert intent.intent == IntentType.UNKNOWN
        assert intent.dimension is None


# ===== Translator tests (7) =====
class TestTranslator:
    def _sql(self, question: str) -> str:
        return SQLTranslator().translate(QueryParser().parse(question))

    def test_ranking_groups_by_product(self):
        assert "GROUP BY product" in self._sql("哪个产品销售额最高")

    def test_ranking_orders_desc(self):
        sql = self._sql("哪个产品销售额最高")
        assert "ORDER BY" in sql and "DESC" in sql

    def test_trend_returns_recent_periods_ascending(self):
        sql = self._sql("智能手表近半年销售额趋势")
        assert "GROUP BY month" in sql
        assert "ORDER BY month DESC" in sql      # 先截取最近 N 期
        assert "ORDER BY dimension ASC" in sql   # 再按时间正序返回给调用方

    def test_comparison_limits_to_two_periods(self):
        assert "LIMIT 2" in self._sql("智能手表销售额环比变化")

    def test_conversion_rate_uses_avg(self):
        sql = self._sql("智能手表转化率变化")
        assert "AVG(conversion_rate)" in sql

    def test_product_filter_lands_in_where(self):
        assert "WHERE product = '智能手表'" in self._sql("智能手表销售额环比变化")

    def test_unsupported_intent_raises(self):
        with pytest.raises(UnsupportedIntentError):
            self._sql("今天天气怎么样")


# ===== Executor tests (8) =====
class TestExecutor:
    def test_allows_select(self, executor):
        result = executor.execute("SELECT COUNT(*) AS n FROM sales")
        assert result.rows[0][0] == 36

    def test_rejects_insert(self, executor):
        with pytest.raises(UnsafeQueryError):
            executor.execute("INSERT INTO sales (month) VALUES ('2026-01')")

    def test_rejects_drop(self, executor):
        with pytest.raises(UnsafeQueryError):
            executor.execute("DROP TABLE sales")

    def test_rejects_unknown_table(self, executor):
        with pytest.raises(UnsafeQueryError):
            executor.execute("SELECT * FROM users")

    def test_rejects_multiple_statements(self, executor):
        with pytest.raises(UnsafeQueryError):
            executor.execute("SELECT * FROM sales; DELETE FROM sales")

    def test_rejects_sql_comment(self, executor):
        with pytest.raises(UnsafeQueryError):
            executor.execute("SELECT * FROM sales -- WHERE 1=1")

    def test_row_cap_truncates(self, db_path):
        limited = SafeQueryExecutor(db_path, max_rows=5)
        result = limited.execute("SELECT month, revenue FROM sales")
        assert result.row_count == 5
        assert result.truncated is True

    def test_records_elapsed_time(self, executor):
        result = executor.execute("SELECT SUM(revenue) AS total FROM sales")
        assert result.elapsed_ms >= 0.0
        assert result.columns == ["total"]


# ===== Loader tests (3) =====
class TestLoader:
    def test_load_demo_dataset(self):
        frame = read_dataset(DEMO_CSV)
        assert len(frame) == 36
        assert "revenue" in frame.columns

    def test_clean_removes_dirty_rows(self):
        raw = read_dataset(DEMO_CSV).head(6).copy()
        dirty = pd.concat([
            raw,
            raw.iloc[[0]],                                  # 完全重复
            raw.iloc[[1]].assign(revenue=float("nan")),      # 关键字段缺失
            raw.iloc[[2]].assign(visitors=0),                # 访客为 0，算不出转化率
        ], ignore_index=True)
        cleaned = clean_dataset(dirty)
        assert len(cleaned) == 6

    def test_clean_recomputes_conversion_rate(self):
        raw = read_dataset(DEMO_CSV).head(6).drop(columns=["conversion_rate"])
        cleaned = clean_dataset(raw)
        assert "conversion_rate" in cleaned.columns
        assert cleaned["conversion_rate"].notna().all()
        expected = round(cleaned.loc[0, "conversions"] / cleaned.loc[0, "visitors"] * 100, 3)
        assert cleaned.loc[0, "conversion_rate"] == pytest.approx(expected, abs=1e-6)


# ===== Analyzer tests (4) =====
class TestAnalyzer:
    def test_ranking_picks_top_product(self):
        intent = QueryIntent(raw="哪个产品销售额最高", intent=IntentType.RANKING,
                             metric=Metric.REVENUE, dimension="product")
        result = QueryResult(columns=["dimension", "metric_value"], rows=[
            ["智能手表", 7101000.0], ["蓝牙耳机", 4000620.0], ["运动手环", 2702420.0],
        ])
        insight = InsightAnalyzer().analyze(intent, result)
        assert insight.title.startswith("智能手表")
        assert insight.value == 7101000.0

    def test_revenue_mom_drop(self):
        intent = QueryIntent(raw="智能手表销售额环比变化", intent=IntentType.COMPARISON,
                             metric=Metric.REVENUE, dimension="month",
                             filters={"product": "智能手表"})
        result = QueryResult(columns=["dimension", "metric_value"], rows=[
            ["2025-12", 401000.0], ["2025-11", 1000000.0],
        ])
        insight = InsightAnalyzer().analyze(intent, result)
        assert insight.change_pct == -59.9
        assert insight.direction == "down"

    def test_conversion_rate_mom_drop(self):
        intent = QueryIntent(raw="智能手表转化率变化", intent=IntentType.COMPARISON,
                             metric=Metric.CONVERSION_RATE, dimension="month")
        result = QueryResult(columns=["dimension", "metric_value"], rows=[
            ["2025-11", 2.0], ["2025-12", 0.894],
        ])
        insight = InsightAnalyzer().analyze(intent, result)
        assert insight.change_pct == -55.3

    def test_large_swing_is_critical(self):
        intent = QueryIntent(raw="智能手表销售额有什么异常", intent=IntentType.ANOMALY,
                             metric=Metric.REVENUE, dimension="month")
        result = QueryResult(columns=["dimension", "metric_value"], rows=[
            ["2025-11", 1000000.0], ["2025-12", 401000.0],
        ])
        insight = InsightAnalyzer().analyze(intent, result)
        assert insight.severity == "critical"


# ===== Visualizer tests (1) =====
class TestVisualizer:
    def test_builds_bar_and_line_figures(self):
        builder = ChartBuilder()
        bar = builder.bar(["A", "B"], [10, 20], title="t", ylabel="y")
        line = builder.line(["A", "B"], [10, 20], title="t", ylabel="y")
        for fig in (bar, line):
            assert isinstance(fig, Figure)
            assert len(fig.axes) == 1


# ===== Integration tests (2) =====
class TestIntegration:
    def test_top_product_end_to_end(self, agent):
        answer = agent.explore("哪个产品销售额最高")
        assert answer["intent"].intent == IntentType.RANKING
        assert answer["rows"][0][0] == "智能手表"
        assert "智能手表" in answer["insight"].title

    def test_mom_comparison_end_to_end(self, agent):
        answer = agent.explore("智能手表销售额环比变化")
        assert answer["row_count"] == 2
        assert answer["insight"].change_pct == -59.9
