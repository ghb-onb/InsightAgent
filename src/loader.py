"""CSV / Excel 读取、列名归一化、清洗，并落地成只读分析库。

设计要点：
1. 列名归一化是**显式**的——每个源列映射到哪个标准列都能打印出来给用户看，
   不是"猜"。映射不上又缺必需列时直接报错，并把可用列名一起吐出来。
2. 必需列只有三列：时间维度、分类维度、金额指标。其余指标缺了只是少一个
   可问的角度，不该拦住整份数据。
3. 归一化只改列名，不删列。用户表里的其他字段原样保留，后续要扩展维度时还在。
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Tuple, Union

import pandas as pd

# 标准列 -> 常见中英文别名。列表靠前的别名在"包含匹配"里优先级更高。
COLUMN_ALIASES: Dict[str, Tuple[str, ...]] = {
    "month": (
        "month", "date", "datetime", "period", "月份", "年月", "日期", "时间",
        "统计月份", "销售月份", "账期", "账单月",
    ),
    "product": (
        "product_name", "product", "item", "sku", "goods", "category",
        "产品名称", "商品名称", "产品", "商品", "品名", "型号", "品类", "类别",
        "门店名称", "店铺名称", "门店", "店铺", "渠道",
    ),
    "revenue": (
        "revenue", "sales_amount", "gmv", "turnover", "销售额", "销售金额",
        "营收", "收入", "成交金额", "成交额", "总金额", "金额",
    ),
    "units_sold": (
        "units_sold", "quantity", "qty", "sales_count", "销售数量", "销量",
        "销售件数", "售出数量", "数量", "件数", "台数",
    ),
    "unit_price": (
        "unit_price", "price", "单价", "售价", "价格", "客单价",
    ),
    "visitors": (
        "visitors", "unique_visitors", "traffic", "访客数", "访客",
        "访问量", "浏览量", "曝光数", "流量",
    ),
    "conversions": (
        "conversions", "order_count", "orders", "成交数", "转化数",
        "成交笔数", "订单数", "成交量", "下单数",
    ),
    "conversion_rate": (
        "conversion_rate", "cvr", "转化率", "成交率", "下单率",
    ),
}

# 必需列：时间 + 分类 + 金额。少任何一个都分析不下去。
REQUIRED_COLUMNS: List[str] = ["month", "product", "revenue"]

NUMERIC_COLUMNS: List[str] = [
    "units_sold", "unit_price", "revenue", "visitors", "conversions", "conversion_rate",
]

# 命中这些词的列名不参与模糊匹配，避免把"退款金额"当成销售额
NEGATIVE_HINTS: Tuple[str, ...] = (
    "退款", "退货", "取消", "优惠", "折扣", "减免", "成本", "费用",
    "税额", "税点", "占比", "比例", "环比", "同比", "增长",
)


# --------------------------------------------------------------------- 归一化


def _normalize_key(name: str) -> str:
    """列名比较用的键：去空白/下划线/括号、转小写。"""
    return re.sub(r"[\s_\-（）()【】\[\]/]+", "", str(name)).lower()


def _is_negative(column: str) -> bool:
    return any(hint in str(column) for hint in NEGATIVE_HINTS)


def map_columns(columns: Iterable[str]) -> Dict[str, str]:
    """推断 {原始列名: 标准列名}，只返回识别成功的列。

    两轮匹配，保证确定性：
      1) 精确匹配别名（去掉分隔符、转小写后完全相等）
      2) 包含匹配，别名越长越优先（"销售金额" 先于 "金额"）
    同一个标准列只会被占用一次，先到先得，避免两列抢一个名字。
    """
    source = {str(col): _normalize_key(col) for col in columns}
    mapping: Dict[str, str] = {}
    taken: set = set()

    for canonical, aliases in COLUMN_ALIASES.items():
        alias_keys = {_normalize_key(alias) for alias in aliases}
        for column, key in source.items():
            if column in mapping or not key:
                continue
            if key in alias_keys:
                mapping[column] = canonical
                taken.add(canonical)
                break

    for canonical, aliases in COLUMN_ALIASES.items():
        if canonical in taken:
            continue
        best: Tuple[int, str] = (0, "")
        for column, key in source.items():
            if column in mapping or _is_negative(column):
                continue
            for alias in aliases:
                alias_key = _normalize_key(alias)
                if len(alias_key) >= 2 and alias_key in key and len(alias_key) > best[0]:
                    best = (len(alias_key), column)
        if best[1]:
            mapping[best[1]] = canonical

    return mapping


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """按别名把列名换成标准列名，未识别的列原样保留。"""
    mapping = map_columns(frame.columns)
    out = frame.rename(columns=mapping).copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def _to_year_month(value: object) -> str:
    """把 2026年1月 / 2026/01 / 2026-01-15 / 202601 统一成 YYYY-MM。"""
    text = str(value).strip()
    match = re.match(r"^(\d{4})\s*[年./\-]\s*(\d{1,2})(?!\d)", text)
    if match and 1 <= int(match.group(2)) <= 12:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    match = re.match(r"^(\d{4})(\d{2})$", text)
    if match and 1 <= int(match.group(2)) <= 12:
        return f"{match.group(1)}-{match.group(2)}"
    return text


# ---------------------------------------------------------------------- 读取


def read_dataset(path: Union[str, Path]) -> pd.DataFrame:
    """读 CSV 或 Excel。按扩展名分派，Excel 走 openpyxl。"""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"数据文件不存在：{file_path}")

    suffix = file_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(file_path)
    if suffix in {".csv", ".txt"}:
        # 中文环境导出的 CSV 常见 GBK，先试 UTF-8，失败再回落
        try:
            return pd.read_csv(file_path)
        except UnicodeDecodeError:
            return pd.read_csv(file_path, encoding="gbk")
    raise ValueError(f"不支持的文件类型：{suffix}，请使用 .csv / .xlsx")


def clean_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """归一化列名 -> 去重 -> 收敛类型 -> 丢脏行 -> 补算转化率 -> 固定排序。

    每一步都是业务上能说清的动作，脏行直接丢弃而不是用魔法值填充。
    """
    out = normalize_columns(df)

    missing = [c for c in REQUIRED_COLUMNS if c not in out.columns]
    if missing:
        raise ValueError(
            f"缺少必需列：{missing}。需要「时间 / 分类 / 金额」三类字段，"
            f"你这份数据的列是 {list(df.columns)}，"
            f"已识别 {map_columns(df.columns) or '无'}。"
            f"把列名改成对应的中文或英文就能自动识别。"
        )

    # 1) 完全重复的行只留一条
    out = out.drop_duplicates()

    # 2) 数值列强制转型，脏数据变 NaN 而不是抛异常
    for column in NUMERIC_COLUMNS:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")

    # 3) 维度列去空白，时间统一成 YYYY-MM
    out["month"] = out["month"].map(_to_year_month)
    out["product"] = out["product"].astype(str).str.strip()

    # 4) 关键字段缺失或明显不合理的行丢弃
    out = out.dropna(subset=["month", "product", "revenue"])
    if "visitors" in out.columns:
        out = out[out["visitors"] > 0]
    if "conversions" in out.columns:
        out = out[out["conversions"] >= 0]
    out = out[out["revenue"] >= 0]
    out = out[out["product"] != ""]
    out = out[out["month"] != ""]

    # 5) 转化率缺失时用 转化数/访客数 回算（单位为百分比）
    if "conversion_rate" not in out.columns:
        out["conversion_rate"] = float("nan")
    if {"conversions", "visitors"}.issubset(out.columns):
        computed = (out["conversions"] / out["visitors"] * 100).round(3)
        out["conversion_rate"] = out["conversion_rate"].fillna(computed)
    else:
        # 原始字段都没有就不留一列 NaN 骗人
        out = out.drop(columns=["conversion_rate"])

    # 6) 固定顺序，保证同样的输入每次产出同样的表
    return out.sort_values(["product", "month"]).reset_index(drop=True)


# ---------------------------------------------------------------------- 入库


def write_frame(frame: pd.DataFrame, db_path: Union[str, Path], table: str = "sales") -> int:
    """把已清洗的 DataFrame 写进 SQLite（覆盖重建），返回行数。"""
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    connection = sqlite3.connect(str(target))
    try:
        frame.to_sql(table, connection, index=False, if_exists="replace")
    finally:
        connection.close()
    return len(frame)


def build_database(
    dataset_path: Union[str, Path],
    db_path: Union[str, Path],
    table: str = "sales",
) -> int:
    """把数据文件清洗后写进 SQLite，返回入库行数。"""
    return write_frame(clean_dataset(read_dataset(dataset_path)), db_path, table)
