"""InsightAgent Demo：内置智能手表销售数据，跑 5 个问题并校验关键指标。

    python run_demo.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agent import InsightAgent
from src.models.query import IntentType
from src.visualizer import ChartBuilder

BASE_DIR = Path(__file__).resolve().parent
DEMO_CSV = BASE_DIR / "demo_data" / "sales_data.csv"
CUSTOM_CSV = BASE_DIR / "demo_data" / "store_sales_cn.csv"
OUTPUT_DIR = BASE_DIR / "demo_output"

QUESTIONS = [
    "哪个产品销售额最高",
    "智能手表销售额环比变化",
    "智能手表转化率变化",
    "蓝牙耳机近半年销售额趋势",
    "三个产品合计销售额是多少",
]

METRIC_LABEL = {
    "revenue": "销售额",
    "units_sold": "销量（台）",
    "visitors": "访客数",
    "conversion_rate": "转化率（%）",
}


def line(char: str = "=", width: int = 66) -> None:
    print(char * width)


def demo_custom_dataset() -> None:
    """附加演示：换一份"别人家"的表（中文列名、店铺维度）也能直接分析。

    这一段是为了证明解析链没有写死 demo 的产品名和英文列名：
    列名靠别名表归一化，分类维度和指标全部从数据里现读。
    """
    line()
    print("  附加演示：换成中文列名、店铺维度的另一份数据")
    line("-")

    agent = InsightAgent(db_path=Path(tempfile.gettempdir()) / "insightagent_demo_cn.db")
    rows = agent.load(CUSTOM_CSV)
    schema = agent.schema

    print(f"  数据源: demo_data/{CUSTOM_CSV.name}  ({rows} 行)")
    print("  列名自动识别:")
    for source, canonical in schema["mapping"].items():
        print(f"    {source}  ->  {canonical}")
    print(f"  分类维度: {schema['dimension_label']} = {schema['products']}")
    print(f"  可问指标: {schema['metrics']}\n")

    for question in (
        f"哪个{schema['dimension_label']}销售额最高",
        f"{schema['products'][0]}销售额环比变化",
    ):
        answer = agent.explore(question)
        print(f"  问：{question}")
        print(f"      {answer['insight'].summary}")
        print()


def main() -> None:
    line()
    print("  InsightAgent Demo - AI 数据分析 Agent")
    line()

    db_path = Path(tempfile.gettempdir()) / "insightagent_demo.db"
    agent = InsightAgent(db_path=db_path)
    rows = agent.load(DEMO_CSV)
    print(f"  数据源: demo_data/sales_data.csv  ({rows} 行 / 3 个产品 / 12 个月)")
    print(f"  只读库: {db_path}\n")

    builder = ChartBuilder()
    answers = []

    # 清掉上一次跑出来的旧图，避免新旧文件混在一起
    if OUTPUT_DIR.exists():
        for stale in OUTPUT_DIR.glob("*.png"):
            stale.unlink()

    for index, question in enumerate(QUESTIONS, start=1):
        answer = agent.explore(question)
        answers.append(answer)
        insight = answer["insight"]
        intent = answer["intent"]

        line("-")
        print(f"[{index}] 问：{question}")
        print(f"    意图: {intent.intent.value} / 指标: {intent.metric.value}")
        print(f"    SQL : {answer['sql'].splitlines()[0]} ...")
        print(f"    结论: {insight.title}")
        print(f"          {insight.summary}")
        if insight.severity != "info":
            print(f"    风险: {insight.severity}")

        if answer["rows"]:
            labels = [str(r[0]) for r in answer["rows"]]
            values = [float(r[1]) for r in answer["rows"]]
            ylabel = METRIC_LABEL.get(intent.metric.value, intent.metric.value)
            # 排名和两期环比用柱状对比更直观，趋势用折线
            if intent.intent in (IntentType.RANKING, IntentType.COMPARISON):
                fig = builder.bar(labels, values, title=question, ylabel=ylabel,
                              highlight_max=intent.intent is IntentType.RANKING)
                name = f"{index:02d}_bar.png"
            else:
                fig = builder.line(labels, values, title=question, ylabel=ylabel)
                name = f"{index:02d}_trend.png"
            OUTPUT_DIR.mkdir(exist_ok=True)
            builder.save(fig, OUTPUT_DIR / name)

    # ------------------------------------------------------------ 关键指标校验
    ranking, revenue_change, cvr_change = answers[0], answers[1], answers[2]
    top_product = ranking["rows"][0][0]
    revenue_pct = revenue_change["insight"].change_pct
    cvr_pct = cvr_change["insight"].change_pct

    line()
    print("  关键指标校验")
    print(f"    销售额最高产品      : {top_product}  {'✓' if top_product == '智能手表' else '✗'}")
    print(f"    智能手表销售额环比  : {revenue_pct:+.1f}%  {'✓' if revenue_pct == -59.9 else '✗'}")
    print(f"    智能手表转化率环比  : {cvr_pct:+.1f}%  {'✓' if cvr_pct == -55.3 else '✗'}")
    line()

    print(f"  图表已保存到 {OUTPUT_DIR.name}/")
    for file in sorted(OUTPUT_DIR.glob("*.png")):
        print(f"    - {file.name}")

    if db_path.exists():
        db_path.unlink()

    demo_custom_dataset()

    print("\n  Demo complete!")


if __name__ == "__main__":
    main()
