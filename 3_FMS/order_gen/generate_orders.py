#!/usr/bin/env python3
"""주문 프로파일과 WMS 마스터로 하루치 outbound JSON을 만든다."""

import argparse
import bisect
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label}는 유한한 숫자여야 함")
    return float(value)


def _histogram(source, label):
    if not isinstance(source, dict):
        raise ValueError(f"{label} 히스토그램이 객체가 아님")
    values, weights = source.get("values"), source.get("weights")
    if not isinstance(values, list) or not isinstance(weights, list) or len(values) != len(weights) or not values:
        raise ValueError(f"{label} values/weights 길이가 잘못됨")
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values):
        raise ValueError(f"{label} 값은 양의 정수여야 함")
    if values != sorted(set(values)):
        raise ValueError(f"{label} 값은 중복 없이 오름차순이어야 함")
    parsed_weights = [_number(weight, f"{label} weight") for weight in weights]
    if any(weight < 0 for weight in parsed_weights) or sum(parsed_weights) <= 0:
        raise ValueError(f"{label} 가중치는 비음수이고 합이 양수여야 함")
    return values, parsed_weights


def _weighted_choice(rng, values, weights):
    total = sum(weights)
    if total <= 0:
        raise ValueError("선택할 양의 가중치가 없음")
    point = rng.random() * total
    cumulative = 0.0
    fallback = None
    for value, weight in zip(values, weights):
        if weight > 0:
            fallback = value
        cumulative += weight
        if point < cumulative:
            return value
    return fallback


def _curve(profile):
    points = profile.get("sku_cumulative")
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError("sku_cumulative 곡선이 없음")
    parsed = []
    for point in points:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError("sku_cumulative 점 형식이 잘못됨")
        parsed.append((_number(point[0], "curve x"), _number(point[1], "curve y")))
    if parsed[0] != (0.0, 0.0) or parsed[-1] != (1.0, 1.0):
        raise ValueError("sku_cumulative는 (0,0)에서 (1,1)까지여야 함")
    if any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in parsed):
        raise ValueError("sku_cumulative 좌표 범위 오류")
    if any(x2 <= x1 or y2 < y1 for (x1, y1), (x2, y2) in zip(parsed, parsed[1:])):
        raise ValueError("sku_cumulative는 x가 증가하고 y가 단조 비감소해야 함")
    return parsed


def _interpolate(points, x):
    xs = [point[0] for point in points]
    right = bisect.bisect_right(xs, x)
    if right == 0:
        return points[0][1]
    if right == len(points):
        return points[-1][1]
    x1, y1 = points[right - 1]
    x2, y2 = points[right]
    return y1 + (y2 - y1) * (x - x1) / (x2 - x1)


def _round_half_up(value):
    return math.floor(value + 0.5)


def _prepare(profile, master, rng):
    line_values, line_weights = _histogram(profile.get("line_count"), "line_count")
    qty_values, qty_weights = _histogram(profile.get("quantity"), "quantity")
    minute_weights = profile.get("minute_weights")
    if not isinstance(minute_weights, list) or len(minute_weights) != 1440:
        raise ValueError("minute_weights는 1440칸이어야 함")
    minute_weights = [_number(weight, "minute weight") for weight in minute_weights]
    if any(weight < 0 for weight in minute_weights) or sum(minute_weights) <= 0:
        raise ValueError("minute_weights는 비음수이고 합이 양수여야 함")
    points = _curve(profile)

    required = {"stores", "products", "racks", "zones"}
    if not isinstance(master, dict) or not required <= master.keys():
        raise ValueError(f"master에는 {sorted(required)} 배열이 필요함")
    if any(not isinstance(master[key], list) for key in required):
        raise ValueError("master 항목은 배열이어야 함")

    def indexed(rows, key, label):
        result = {}
        for row in rows:
            if not isinstance(row, dict) or key not in row:
                raise ValueError(f"{label} 행에 {key}가 없음")
            identity = row[key]
            if identity in result:
                raise ValueError(f"중복 {label} ID: {identity}")
            result[identity] = row
        if not result:
            raise ValueError(f"{label}가 비어 있음")
        return result

    stores = indexed(master["stores"], "store_id", "store")
    products = indexed(master["products"], "product_id", "product")
    racks = indexed(master["racks"], "rack_id", "rack")
    zones = indexed(master["zones"], "zone_id", "zone")
    fields = set()
    warehouse_ids = set()
    for zone in zones.values():
        if "warehouse_id" not in zone or "facility_id" not in zone:
            raise ValueError("zone에 warehouse_id/facility_id가 없음")
        warehouse_ids.add(zone["warehouse_id"])
    if len(warehouse_ids) != 1:
        raise ValueError("master는 단일 창고여야 함")
    for rack in racks.values():
        if rack.get("zone_id") not in zones or not isinstance(rack.get("field"), str) or not rack["field"]:
            raise ValueError(f"rack 참조/field 오류: {rack!r}")
        if rack["field"] in fields:
            raise ValueError(f"중복 rack field: {rack['field']}")
        fields.add(rack["field"])
    for store in stores.values():
        if store.get("zone_id") not in zones:
            raise ValueError(f"store의 zone 참조 오류: {store!r}")

    products_by_store = defaultdict(list)
    for product in products.values():
        store = stores.get(product.get("store_id"))
        rack = racks.get(product.get("rack_id"))
        if store is None or rack is None:
            raise ValueError(f"product 참조 오류: {product!r}")
        if store["zone_id"] != rack["zone_id"]:
            raise ValueError(f"product의 매장과 rack zone 불일치: {product['product_id']}")
        products_by_store[product["store_id"]].append(product)

    ranked = sorted(products.values(), key=lambda product: product["product_id"])
    rng.shuffle(ranked)
    count = len(ranked)
    popularity = {}
    previous = 0.0
    for rank, product in enumerate(ranked, 1):
        cumulative = _interpolate(points, rank / count)
        popularity[product["product_id"]] = max(0.0, cumulative - previous)
        previous = cumulative
    if sum(popularity.values()) <= 0:
        raise ValueError("상품 인기 가중치 합이 0임")

    outbound_values = [store.get("outbound_count") for store in stores.values()]
    if all(value is None for value in outbound_values):
        store_factor = {store_id: 1.0 for store_id in stores}
    elif any(value is None for value in outbound_values):
        raise ValueError("outbound_count는 전부 있거나 전부 없어야 함")
    else:
        parsed = {store_id: _number(store["outbound_count"], "outbound_count")
                  for store_id, store in stores.items()}
        if any(value < 0 for value in parsed.values()) or sum(parsed.values()) <= 0:
            raise ValueError("outbound_count는 비음수이고 전체 합이 양수여야 함")
        total = sum(parsed.values())
        store_factor = {store_id: value / total for store_id, value in parsed.items()}

    global_weights = {
        product_id: popularity[product_id] * store_factor[product["store_id"]]
        for product_id, product in products.items()
    }
    selectable_stores = {products[product_id]["store_id"] for product_id, weight in global_weights.items() if weight > 0}
    if not selectable_stores:
        raise ValueError("전역 가중치가 양수인 상품이 없음")
    max_line_count = max(line_values)
    for store_id in selectable_stores:
        store_products = products_by_store[store_id]
        needed = min(max_line_count, len(store_products))
        available = sum(popularity[product["product_id"]] > 0 for product in store_products)
        if available < needed:
            raise ValueError(f"store {store_id}의 양의 상품 가중치가 부족함: {available} < {needed}")

    ratios = profile.get("abc_ratios", [0.21, 0.34, 0.45])
    if ratios != [0.21, 0.34, 0.45]:
        raise ValueError("V1 abc_ratios는 [0.21, 0.34, 0.45]여야 함")
    a_count = _round_half_up(0.21 * count)
    b_count = _round_half_up(0.34 * count)
    abc = {
        "A": sorted(product["product_id"] for product in ranked[:a_count]),
        "B": sorted(product["product_id"] for product in ranked[a_count:a_count + b_count]),
        "C": sorted(product["product_id"] for product in ranked[a_count + b_count:]),
    }
    return {
        "line_values": line_values, "line_weights": line_weights,
        "qty_values": qty_values, "qty_weights": qty_weights,
        "minute_weights": minute_weights, "points": points,
        "stores": stores, "products": products, "racks": racks,
        "products_by_store": products_by_store, "ranked": ranked,
        "popularity": popularity, "global_weights": global_weights,
        "abc": abc,
    }


def generate(profile, master, orders, seed=42, release="wave"):
    """profile + master + N + seed → 출력 JSON dict. 진단이 필요하면 generate_with_context() 뒤 diagnostics()."""
    return generate_with_context(profile, master, orders, seed, release)[0]


def generate_with_context(profile, master, orders, seed=42, release="wave"):
    """(결과 dict, 준비 컨텍스트). 컨텍스트는 diagnostics() 입력이다."""
    if isinstance(orders, bool) or not isinstance(orders, int) or orders < 0:
        raise ValueError("orders는 0 이상의 정수여야 함")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed는 정수여야 함")
    if release not in ("wave", "smooth"):
        raise ValueError("release는 wave 또는 smooth여야 함")

    content_rng = random.Random(seed)
    release_rng = random.Random(seed + 1)
    context = _prepare(profile, master, content_rng)
    product_ids = sorted(context["products"])
    global_weights = [context["global_weights"][product_id] for product_id in product_ids]
    hour_weights = [sum(context["minute_weights"][hour * 60:(hour + 1) * 60]) for hour in range(24)]
    generated = []
    clipped_orders = dropped_lines = 0

    for sequence in range(orders):
        original_k = _weighted_choice(content_rng, context["line_values"], context["line_weights"])
        first_id = _weighted_choice(content_rng, product_ids, global_weights)
        first = context["products"][first_id]
        candidates = sorted(context["products_by_store"][first["store_id"]], key=lambda item: item["product_id"])
        effective_k = min(original_k, len(candidates))
        if effective_k < original_k:
            clipped_orders += 1
            dropped_lines += original_k - effective_k
        selected = [first]
        remaining = [product for product in candidates if product["product_id"] != first_id]
        while len(selected) < effective_k:
            weights = [context["popularity"][product["product_id"]] for product in remaining]
            choice = _weighted_choice(content_rng, remaining, weights)
            selected.append(choice)
            remaining.remove(choice)
        lines = []
        for product in sorted(selected, key=lambda item: item["product_id"]):
            quantity = _weighted_choice(content_rng, context["qty_values"], context["qty_weights"])
            rack = context["racks"][product["rack_id"]]
            lines.append({"product_id": product["product_id"], "rack_id": rack["field"], "qty": quantity})

        if release == "wave":
            minute = _weighted_choice(release_rng, range(1440), context["minute_weights"])
            ordered_at_s = minute * 60 + release_rng.randrange(60)
        else:
            hour = _weighted_choice(release_rng, range(24), hour_weights)
            ordered_at_s = hour * 3600 + release_rng.randrange(3600)
        generated.append({"_sequence": sequence, "_first_product_id": first_id, "store_id": first["store_id"],
                          "ordered_at_s": ordered_at_s, "lines": lines})

    generated.sort(key=lambda order: (order["ordered_at_s"], order["_sequence"]))
    first_products = []
    for order_id, order in enumerate(generated, 1):
        order["order_id"] = order_id
        first_products.append(order.pop("_first_product_id"))
        del order["_sequence"]
    context["first_products"] = first_products      # 진단용: 주문별 첫 라인 상품 (출력에는 없음)
    lines_total = sum(len(order["lines"]) for order in generated)
    units_total = sum(line["qty"] for order in generated for line in order["lines"])
    result = {
        "meta": {
            "abc": context["abc"],
            "clipped_orders": clipped_orders,
            "dropped_lines": dropped_lines,
            "lines": lines_total,
            "orders": orders,
            "profile": profile.get("profile", "unknown"),
            "release": release,
            "seed": seed,
            "units": units_total,
        },
        "outbound": generated,
    }
    return result, context


def _ratios(counter, total):
    """[[값, 비율], …] 를 값 기준 숫자 정렬로. dict 로 두면 json sort_keys 가 '1','10','11' 순으로 흩는다."""
    return [[key, round(value / total, 6)] for key, value in sorted(counter.items())] if total else []


def diagnostics(result, context):
    orders = result["outbound"]
    line_counter = Counter(len(order["lines"]) for order in orders)
    qty_counter = Counter(line["qty"] for order in orders for line in order["lines"])
    store_counter = Counter(order["store_id"] for order in orders)
    minute_counter = Counter(order["ordered_at_s"] // 60 for order in orders)
    hour_counter = Counter(order["ordered_at_s"] // 3600 for order in orders)
    total_orders = len(orders)
    total_lines = sum(line_counter.values())

    store_mass = Counter()
    for product_id, weight in context["global_weights"].items():
        store_mass[context["products"][product_id]["store_id"]] += weight
    mass_total = sum(store_mass.values())
    expected = Counter()
    line_weight_total = sum(context["line_weights"])
    for store_id, mass in store_mass.items():
        product_count = len(context["products_by_store"][store_id])
        for value, weight in zip(context["line_values"], context["line_weights"]):
            expected[min(value, product_count)] += mass / mass_total * weight / line_weight_total

    qty_by_product = Counter()
    for order in orders:
        for line in order["lines"]:
            qty_by_product[line["product_id"]] += line["qty"]
    top_count = math.ceil(0.2 * len(context["ranked"]))
    top_ids = {product["product_id"] for product in context["ranked"][:top_count]}
    all_qty = sum(qty_by_product.values())
    top_share = sum(qty_by_product[product_id] for product_id in top_ids) / all_qty if all_qty else 0.0
    # 첫 라인만의 상위 20 % 비율 — 전역 가중치(p×b)의 효과. 전체 점유와의 차이가 2라인 이후 매장 안 추출의 희석분이다.
    first_products = context.get("first_products", [])
    first_top_share = (sum(product_id in top_ids for product_id in first_products) / len(first_products)
                       if first_products else 0.0)
    target_line = [[value, round(weight / line_weight_total, 6)]
                   for value, weight in zip(context["line_values"], context["line_weights"])]
    qty_weight_total = sum(context["qty_weights"])
    target_qty = [[value, round(weight / qty_weight_total, 6)]
                  for value, weight in zip(context["qty_values"], context["qty_weights"])]
    return {
        "generated": {
            "hour_share": _ratios(hour_counter, total_orders),
            "line_share": _ratios(line_counter, total_orders),
            "minute_share": _ratios(minute_counter, total_orders),
            "qty_share": _ratios(qty_counter, total_lines),
            "store_share": _ratios(store_counter, total_orders),
            "top_20_pct_sku_qty_share": round(top_share, 6),
            "top_20_pct_sku_first_line_share": round(first_top_share, 6),
        },
        "target": {
            "constrained_line_share": [[key, round(value, 6)] for key, value in sorted(expected.items())],
            "line_share": target_line,
            "qty_share": target_qty,
            "top_20_pct_sku_qty_share": round(_interpolate(context["points"], top_count / len(context["ranked"])), 6),
        },
    }


def load_json(path):
    with open(path, encoding="utf-8") as source:
        return json.load(source)


def write_json(data, destination):
    json.dump(data, destination, ensure_ascii=False, sort_keys=True, indent=2)
    destination.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--master", required=True, type=Path)
    parser.add_argument("--orders", required=True, type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--release", choices=("wave", "smooth"), default="wave")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", "-o", type=Path, help="저장할 주문 JSON (기본: stdout)")
    args = parser.parse_args(argv)
    try:
        result, context = generate_with_context(load_json(args.profile), load_json(args.master), args.orders,
                                                seed=args.seed, release=args.release)
        if args.check:
            write_json(diagnostics(result, context), sys.stderr)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w", encoding="utf-8", newline="\n") as destination:
                write_json(result, destination)
        else:
            write_json(result, sys.stdout)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
