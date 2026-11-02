"""Streamlit 交互界面：上传数据 -> 提问 -> 看表 / 看结论 / 看图。

启动： streamlit run src/app.py
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from src.agent import InsightAgent
from src.loader import clean_dataset, read_dataset
from src.models.query import IntentType
from src.visualizer import ChartBuilder

st.set_page_config(page_title="InsightAgent", page_icon="📊", layout="wide")

DEMO_FILE = Path(__file__).resolve().parent.parent / "demo_data" / "sales_data.csv"

SAMPLE_QUESTIONS = [
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


@st.cache_resource(show_spinner=False)
def _build_agent(source_path: str, mtime: float) -> InsightAgent:
    """按文件路径 + 修改时间缓存，换了文件就重建。"""
    db_path = Path(tempfile.gettempdir()) / "insightagent_streamlit.db"
    agent = InsightAgent(db_path=db_path)
    agent.load(source_path)
    return agent


def main() -> None:
    st.title("📊 InsightAgent")
    st.caption("上传销售明细，用中文提问，自动生成安全 SQL 并给出结论与图表")

    with st.sidebar:
        st.header("数据源")
        uploaded = st.file_uploader("上传 CSV / Excel", type=["csv", "xlsx", "xls"])
        use_demo = st.checkbox("使用内置 Demo 数据（智能手表销售）", value=uploaded is None)

        st.divider()
        st.header("示例问题")
        for question in SAMPLE_QUESTIONS:
            st.caption(f"· {question}")

    # ---------------------------------------------------------------- 数据加载
    if uploaded is not None:
        suffix = Path(uploaded.name).suffix or ".csv"
        tmp = Path(tempfile.gettempdir()) / f"insightagent_upload{suffix}"
        tmp.write_bytes(uploaded.getbuffer())
        source = tmp
    elif use_demo and DEMO_FILE.exists():
        source = DEMO_FILE
    else:
        st.info("请在左侧上传数据文件，或勾选使用内置 Demo 数据。")
        return

    try:
        agent = _build_agent(str(source), source.stat().st_mtime)
        frame = clean_dataset(read_dataset(source))
    except Exception as exc:  # noqa: BLE001 - 界面上要显示失败原因
        st.error(f"数据加载失败：{exc}")
        return

    st.success(f"已加载 {len(frame)} 行数据 · {frame['product'].nunique()} 个产品")
    with st.expander("预览清洗后的数据", expanded=False):
        st.dataframe(frame.head(50), use_container_width=True)

    # ------------------------------------------------------------------ 提问区
    question = st.text_input("你想问什么？", value=SAMPLE_QUESTIONS[0])
    if not question.strip():
        return

    try:
        answer = agent.explore(question)
    except Exception as exc:  # noqa: BLE001 - 无法理解的问题要给出提示
        st.warning(f"这个问题暂时回答不了：{exc}")
        return

    insight = answer["insight"]
    intent = answer["intent"]

    st.subheader(insight.title)
    if insight.severity == "critical":
        st.error(insight.summary)
    elif insight.severity == "warning":
        st.warning(insight.summary)
    else:
        st.info(insight.summary)

    metric_col, change_col, row_col = st.columns(3)
    if insight.value is not None:
        metric_col.metric("当前值", f"{insight.value:,.2f}")
    if insight.change_pct is not None:
        change_col.metric("环比", f"{insight.change_pct:+.1f}%")
    row_col.metric("命中行数", answer["row_count"])

    # ------------------------------------------------------------------ 可视化
    rows = answer["rows"]
    if rows:
        labels = [str(r[0]) for r in rows]
        values = [float(r[1]) for r in rows]
        builder = ChartBuilder()

        if intent.intent in (IntentType.RANKING, IntentType.COMPARISON):
            fig = builder.bar(
                labels, values, title=question,
                ylabel=METRIC_LABEL.get(str(intent.metric.value), ""),
                highlight_max=intent.intent is IntentType.RANKING,
            )
        else:
            fig = builder.line(labels, values, title=question, ylabel=METRIC_LABEL.get(str(intent.metric.value), ""))

        st.pyplot(fig)

        with st.expander("查看数据表与生成的 SQL", expanded=False):
            st.dataframe(pd.DataFrame(rows, columns=answer["columns"]), use_container_width=True)
            st.code(answer["sql"], language="sql")
            st.caption(f"耗时 {answer['elapsed_ms']:.2f} ms")


if __name__ == "__main__":
    main()
