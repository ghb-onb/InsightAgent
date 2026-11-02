"""Deterministic generator for the InsightAgent demo dataset.

Run:  python demo_data/generate_demo_data.py
Out:  demo_data/sales_data.csv

数据设计说明（这是 demo 的关键，改动要同步改 README 与测试）：
- 三个产品 12 个月的销售明细，智能手表全年销售额最高；
- 智能手表 2025-11 是双11 冲高（1000 台 / 100 万），2025-12 回落（401 台 / 40.1 万）
  => 环比 -59.9%
- 智能手表转化率 11月 2.0% -> 12月 0.894%
  => 环比 -55.3%
所以 demo 里"哪个产品销售额最高""环比变化""转化率变化"有确定答案。
"""
from __future__ import annotations

import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUT_FILE = BASE_DIR / "sales_data.csv"

MONTHS = [f"2025-{m:02d}" for m in range(1, 13)]

PRODUCTS = [
    {
        "product": "智能手表",
        "category": "可穿戴设备",
        "unit_price": 1000.0,
        "units": [480, 520, 560, 540, 580, 620, 590, 610, 560, 640, 1000, 401],
        "visitors": [80000, 82000, 85000, 83000, 88000, 90000, 92000, 95000, 90000, 96000, 100000, 100000],
        "cvr": [1.80, 1.90, 2.00, 1.95, 2.05, 2.10, 2.00, 2.15, 1.90, 2.20, 2.00, 0.894],
    },
    {
        "product": "蓝牙耳机",
        "category": "音频设备",
        "unit_price": 299.0,
        "units": [900, 950, 1000, 1050, 1100, 1150, 1200, 1250, 1180, 1300, 1600, 700],
        "visitors": [60000, 62000, 65000, 66000, 68000, 70000, 72000, 74000, 70000, 76000, 90000, 65000],
        "cvr": [3.00, 3.10, 3.20, 3.00, 3.30, 3.40, 3.20, 3.50, 3.10, 3.60, 3.80, 2.50],
    },
    {
        "product": "运动手环",
        "category": "可穿戴设备",
        "unit_price": 199.0,
        "units": [1000, 1050, 1100, 1080, 1120, 1150, 1180, 1200, 1150, 1250, 1500, 800],
        "visitors": [40000, 41000, 42000, 41500, 43000, 44000, 45000, 46000, 44000, 47000, 55000, 42000],
        "cvr": [4.00, 4.10, 4.20, 4.00, 4.30, 4.40, 4.20, 4.50, 4.10, 4.60, 4.80, 3.20],
    },
]

HEADER = [
    "month", "product", "category", "units_sold", "unit_price",
    "revenue", "visitors", "conversions", "conversion_rate",
]


def main() -> None:
    rows = []
    for p in PRODUCTS:
        for i, month in enumerate(MONTHS):
            units = p["units"][i]
            price = p["unit_price"]
            visitors = p["visitors"][i]
            # 转化人数按目标转化率取整，转化率再由人数/访客回算，保证内部自洽
            conversions = round(visitors * p["cvr"][i] / 100)
            conversion_rate = round(conversions / visitors * 100, 3)
            rows.append([
                month, p["product"], p["category"], units, price,
                round(units * price, 2), visitors, conversions, conversion_rate,
            ])

    rows.sort(key=lambda r: (r[1], r[0]))

    with open(OUT_FILE, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        writer.writerows(rows)

    print(f"wrote {len(rows)} rows -> {OUT_FILE}")


if __name__ == "__main__":
    main()
