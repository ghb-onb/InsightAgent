"""Matplotlib 图表构建。函数式返回 Figure，不依赖 pyplot 全局状态。"""
from __future__ import annotations

from typing import Sequence, Union

import matplotlib

matplotlib.use("Agg")  # 无显示环境（CI / 服务端）也能出图

from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

# 中文字体：Windows 用雅黑，Linux/mac 回退，最后兜底 DejaVu
matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei", "PingFang SC", "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False

PALETTE = "#3B6FD4"
PALETTE_HIGHLIGHT = "#E45756"

# 超过这个量级就用「万」做刻度单位，避免轴标签变成 1e6
WAN_THRESHOLD = 10_000


def _wan_formatter(max_value: float):
    """把刻度格式化成业务可读的写法。

    - 大额（>=1万）：用「万」为单位，避免出现 1e6；
    - 小数（<10，例如转化率）：保留两位小数再裁掉多余的 0；
    - 其余：千分位整数。
    """

    def format_tick(value, _position):
        if max_value >= WAN_THRESHOLD:
            return f"{value / WAN_THRESHOLD:,.0f}万"
        if max_value < 10:
            text = f"{value:.2f}".rstrip("0").rstrip(".")
            return text or "0"
        return f"{value:,.0f}"

    return FuncFormatter(format_tick)


class ChartBuilder:
    """把 (labels, values) 画成柱状图或折线图。"""

    def bar(
        self,
        labels: Sequence[str],
        values: Sequence[float],
        title: str = "",
        ylabel: str = "",
        highlight_max: bool = True,
    ) -> Figure:
        fig = Figure(figsize=(8, 4.5), dpi=120)
        ax = fig.add_subplot(111)

        colors = [PALETTE] * len(values)
        if highlight_max and values:
            colors[list(values).index(max(values))] = PALETTE_HIGHLIGHT

        ax.bar([str(x) for x in labels], list(values), color=colors, width=0.6)
        self._decorate(ax, title, ylabel, values)
        ax.tick_params(axis="x", rotation=0)
        fig.tight_layout()
        return fig

    def line(
        self,
        labels: Sequence[str],
        values: Sequence[float],
        title: str = "",
        ylabel: str = "",
        marker: bool = True,
    ) -> Figure:
        fig = Figure(figsize=(9, 4.5), dpi=120)
        ax = fig.add_subplot(111)

        ax.plot(
            [str(x) for x in labels], list(values),
            color=PALETTE, linewidth=2.0,
            marker="o" if marker else None, markersize=4,
        )
        ax.fill_between(
            range(len(values)), list(values),
            min(values) * 0.98 if values else 0,
            color=PALETTE, alpha=0.10,
        )
        self._decorate(ax, title, ylabel, values)
        if len(labels) > 6:
            ax.tick_params(axis="x", rotation=45)
        fig.tight_layout()
        return fig

    @staticmethod
    def save(fig: Figure, path: Union[str, "object"]) -> str:
        target = str(path)
        fig.savefig(target, bbox_inches="tight")
        return target

    @staticmethod
    def _decorate(ax, title: str, ylabel: str, values: Sequence[float]) -> None:
        if title:
            ax.set_title(title, fontsize=13, pad=12, color="#1F2937")
        if ylabel:
            ax.set_ylabel(ylabel, fontsize=10, color="#4B5563")

        max_value = max((abs(v) for v in values), default=0)
        ax.yaxis.set_major_formatter(_wan_formatter(max_value))

        ax.grid(axis="y", linestyle="--", alpha=0.35)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color("#D1D5DB")
