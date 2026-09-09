#!/usr/bin/env python3
"""Mendeley Customer_Order.csv에서 주문 생성기 프로파일을 추출한다."""

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


HEADERS = (
    "codCustomer", "orderNumber", "orderToCollect", "Reference", "Size (US)",
    "quantity (units)", "creationDate", "waveNumber", "operator",
)
REQUIRED_VALUES = ("codCustomer", "orderNumber", "Reference", "quantity (units)", "creationDate")
DATE_FORMAT = "%d/%m/%Y %H:%M"
SOURCE = {
    "title": "Order Picking Dataset from a Warehouse of a Footwear Manufacturing Company",
    "url": "https://data.mendeley.com/datasets/pf2w725pw3/1",
    "doi": "10.17632/pf2w725pw3.1",
    "license": "CC BY 4.0",
    "file": "Customer_Order.csv",
}


def _histogram(values):
    counts = Counter(values)
    keys = sorted(counts)
    return {"values": keys, "weights": [counts[key] for key in keys]}


def _percentile(values, fraction):
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * fraction) - 1]


def _share_at(curve, fraction):
    index = math.ceil((len(curve) - 1) * fraction)
    return curve[index][1]


def extract_profile(csv_path):
    """CSV를 검증·정제하고 JSON 직렬화 가능한 프로파일을 반환한다."""
    raw_rows = []
    with open(csv_path, encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, delimiter=";")
        if tuple(reader.fieldnames or ()) != HEADERS:
            raise ValueError(f"CSV 열이 예상과 다름: {reader.fieldnames!r}")
        for line_number, source_row in enumerate(reader, 2):
            row = {key: source_row[key].strip() for key in HEADERS}
            missing = [key for key in REQUIRED_VALUES if not row[key]]
            if missing:
                raise ValueError(f"{line_number}행 필수 값 누락: {', '.join(missing)}")
            try:
                quantity = int(row["quantity (units)"])
            except ValueError as exc:
                raise ValueError(f"{line_number}행 quantity가 정수가 아님") from exc
            try:
                created_at = datetime.strptime(row["creationDate"], DATE_FORMAT)
            except ValueError as exc:
                raise ValueError(f"{line_number}행 creationDate 형식 오류") from exc
            raw_rows.append((row, quantity, created_at))

    if not raw_rows:
        raise ValueError("데이터 행이 없음")

    order_identity = defaultdict(lambda: (set(), set()))
    for row, _, created_at in raw_rows:
        customers, times = order_identity[row["orderNumber"]]
        customers.add(row["codCustomer"])
        times.add(created_at)
    conflicts = [order for order, (customers, times) in order_identity.items()
                 if len(customers) != 1 or len(times) != 1]
    if conflicts:
        raise ValueError(f"주문 ID의 고객·시각 충돌: {conflicts[:5]}")

    raw_seen = set()
    raw_duplicate_rows = 0
    for row, _, _ in raw_rows:
        key = tuple(row[column] for column in HEADERS)
        raw_duplicate_rows += key in raw_seen
        raw_seen.add(key)

    positive_rows = []
    nonpositive_rows = 0
    for parsed in raw_rows:
        if parsed[1] <= 0:
            nonpositive_rows += 1
        else:
            positive_rows.append(parsed)

    clean_rows = []
    seen = set()
    duplicate_rows_removed = 0
    duplicate_qty_removed = 0
    for row, quantity, created_at in positive_rows:
        key = tuple(row[column] for column in HEADERS)
        if key in seen:
            duplicate_rows_removed += 1
            duplicate_qty_removed += quantity
            continue
        seen.add(key)
        clean_rows.append((row, quantity, created_at))

    line_qty = defaultdict(int)
    order_time = {}
    sku_qty = Counter()
    customers = set()
    for row, quantity, created_at in clean_rows:
        order = row["orderNumber"]
        reference = row["Reference"]
        line_qty[(order, reference)] += quantity
        order_time[order] = created_at
        sku_qty[reference] += quantity
        customers.add(row["codCustomer"])

    lines_per_order = Counter()
    for order, _ in line_qty:
        lines_per_order[order] += 1
    line_counts = list(lines_per_order.values())
    quantities = list(line_qty.values())
    if not line_counts or not quantities or not sku_qty:
        raise ValueError("정제 후 유효 주문이 없음")

    minute_weights = [0] * 1440
    for order in lines_per_order:
        created_at = order_time[order]
        minute_weights[created_at.hour * 60 + created_at.minute] += 1

    ranked_sku_qty = sorted(sku_qty.values(), reverse=True)
    total_qty = sum(ranked_sku_qty)
    sku_cumulative = [[0.0, 0.0]]
    cumulative = 0
    sku_count = len(ranked_sku_qty)
    for rank, quantity in enumerate(ranked_sku_qty, 1):
        cumulative += quantity
        sku_cumulative.append([round(rank / sku_count, 12), round(cumulative / total_qty, 12)])
    sku_cumulative[-1] = [1.0, 1.0]

    dates = {order_time[order].date() for order in lines_per_order}
    raw_orders = set(order_identity)
    valid_orders = set(lines_per_order)
    summary = {
        "line_mean": round(sum(line_counts) / len(line_counts), 4),
        "line_p90": _percentile(line_counts, 0.9),
        "line_over_6_ratio": round(sum(value > 6 for value in line_counts) / len(line_counts), 6),
        "qty_mean": round(sum(quantities) / len(quantities), 4),
        "qty_p90": _percentile(quantities, 0.9),
        "top_20_pct_sku_qty_share": round(_share_at(sku_cumulative, 0.2), 6),
        "top_50_pct_sku_qty_share": round(_share_at(sku_cumulative, 0.5), 6),
    }
    return {
        "profile": "order_rules",
        "source": SOURCE,
        "stats": {
            "raw_rows": len(raw_rows),
            "valid_rows": len(clean_rows),
            "nonpositive_rows_removed": nonpositive_rows,
            "raw_duplicate_rows": raw_duplicate_rows,
            "duplicate_rows_removed": duplicate_rows_removed,
            "duplicate_qty_removed": duplicate_qty_removed,
            "orders_raw": len(raw_orders),
            "orders": len(valid_orders),
            "orders_without_valid_lines": len(raw_orders - valid_orders),
            "lines": len(line_qty),
            "products": len(sku_qty),
            "customers": len(customers),
            "business_days": len(dates),
            "period_start": min(dates).isoformat(),
            "period_end": max(dates).isoformat(),
        },
        "summary": summary,
        "line_count": _histogram(line_counts),
        "quantity": _histogram(quantities),
        "sku_cumulative": sku_cumulative,
        "minute_weights": minute_weights,
        "abc_ratios": [0.21, 0.34, 0.45],
    }


def write_json(data, destination):
    json.dump(data, destination, ensure_ascii=False, sort_keys=True, indent=2)
    destination.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="Customer_Order.csv 경로")
    parser.add_argument("--output", "-o", type=Path, help="저장할 프로파일 JSON (기본: stdout)")
    args = parser.parse_args(argv)
    try:
        profile = extract_profile(args.csv)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w", encoding="utf-8", newline="\n") as destination:
                write_json(profile, destination)
        else:
            write_json(profile, sys.stdout)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
