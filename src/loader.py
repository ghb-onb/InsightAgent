"""CSV / Excel 读取、清洗，并落地成只读分析库。"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Union

import pandas as pd

REQUIRED_COLUMNS: List[str] = [
    "month", "product", "units_sold", "unit_price", "revenue", "visitors", "conversions",
]

NUMERIC_COLUMNS: List[str] = [
    "units_sold", "unit_price", "revenue", "visitors", "conversions", "conversion_rate",
]


def read_dataset(path: Union[str, Path]) -> pd.DataFrame:
    """读 CSV 或 Excel。按扩展名分派，Excel 走 openpyxl。"""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"数据文件不存在：{file_path}")

    suffix = file_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(file_path)
    if suffix in {".csv", ".txt"}:
        return pd.read_csv(file_path)
    raise ValueError(f"不支持的文件类型：{suffix}，请使用 .csv / .xlsx")


def clean_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """清洗：去重、类型收敛、丢脏行、补算转化率、排序。

    这里刻意保持"可解释"——每一步都是业务上能说清楚的动作，
    不用魔法填值，脏行直接丢弃并在 README 里说明。
    """
    out = df.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in out.columns]
    if missing:
        raise ValueError(f"缺少必需列：{missing}")

    # 1) 完全重复的行只留一条
    out = out.drop_duplicates()

    # 2) 数值列强制转型，脏数据变 NaN 而不是抛异常
    for column in NUMERIC_COLUMNS:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")

    # 3) 文本列去空白
    out["month"] = out["month"].astype(str).str.strip()
    out["product"] = out["product"].astype(str).str.strip()

    # 4) 关键字段缺失或明显不合理的行丢弃
    out = out.dropna(subset=["month", "product", "revenue", "visitors", "conversions"])
    out = out[out["visitors"] > 0]
    out = out[out["revenue"] >= 0]

    # 5) 转化率缺失时用 转化数/访客数 回算（单位为百分比）
    if "conversion_rate" not in out.columns:
        out["conversion_rate"] = float("nan")
    computed = (out["conversions"] / out["visitors"] * 100).round(3)
    out["conversion_rate"] = out["conversion_rate"].fillna(computed)

    # 6) 固定顺序，保证同样的输入每次产出同样的表
    return out.sort_values(["product", "month"]).reset_index(drop=True)


def build_database(
    dataset_path: Union[str, Path],
    db_path: Union[str, Path],
    table: str = "sales",
) -> int:
    """把数据文件清洗后写进 SQLite，返回入库行数。"""
    frame = clean_dataset(read_dataset(dataset_path))

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
