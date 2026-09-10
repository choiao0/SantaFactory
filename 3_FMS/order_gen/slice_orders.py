#!/usr/bin/env python3
"""하루치 주문 JSON 에서 시간창 [start, end) 만 잘라 시각을 start 기준으로 옮긴다 (-156).

시뮬 `--orders-file` 은 ordered_at_s 를 시뮬 시작 기준 초로 읽고 horizon 밖은 버리므로, 하루치를 그대로 넣으면
00:00 부터 horizon 만큼만 본다. 피크 창(예: 07:00~09:00)을 돌리려면 여기서 자르고 horizon_s = end - start 로 넘긴다.

    python slice_orders.py day.json --start 07:00 --end 09:00 -o win.json
    (start/end 는 HH:MM 또는 초. stderr 에 horizon_s 와 건수를 출력)
"""

import argparse
import json
import sys
from pathlib import Path


def to_seconds(text):
    if ":" in text:
        h, m = text.split(":")
        return int(h) * 3600 + int(m) * 60
    return int(text)


def slice_orders(data, start, end):
    """data = 생성기 출력({meta, outbound}) 또는 outbound 리스트. [start, end) 주문만, 시각 -= start."""
    if not 0 <= start < end <= 86400:
        raise ValueError(f"창은 0 <= start < end <= 86400: {start}, {end}")
    orders = data["outbound"] if isinstance(data, dict) else data
    kept = [dict(o, ordered_at_s=o["ordered_at_s"] - start) for o in orders if start <= o["ordered_at_s"] < end]
    meta = dict(data.get("meta", {})) if isinstance(data, dict) else {}
    meta.update(window_start_s=start, window_end_s=end, horizon_s=end - start,
                orders_in_window=len(kept), orders_total=len(orders))
    return {"meta": meta, "outbound": kept}


def rescale_orders(data, start, end):
    """주문 시각 구간(첫 주문~마지막 주문+1 s)을 [start, end) 로 선형 비례 매핑 (-158).

    생성기 시각은 참조 창고 분포(07시 피크)를 따르는데 견적 대상 창고의 출고 시간대는 다르다. 백엔드는
    "하루 물량이 출고 창 안에 전부 들어온다"로 간격을 계산하므로 같은 전제로 맞춘다 — 몰림 모양은 그대로,
    밀도 = 하루 물량 ÷ 출고 창. 정렬 순서는 유지되고 결과 시각은 항상 end 미만이다.
    """
    if not 0 <= start < end <= 86400:
        raise ValueError(f"창은 0 <= start < end <= 86400: {start}, {end}")
    orders = data["outbound"] if isinstance(data, dict) else data
    meta = dict(data.get("meta", {})) if isinstance(data, dict) else {}
    if not orders:
        return {"meta": meta, "outbound": []}
    lo = min(o["ordered_at_s"] for o in orders)
    hi = max(o["ordered_at_s"] for o in orders) + 1
    scale = (end - start) / (hi - lo)
    moved = [dict(o, ordered_at_s=start + int((o["ordered_at_s"] - lo) * scale)) for o in orders]
    meta.update(rescaled_from_s=[lo, hi], rescaled_to_s=[start, end])
    return {"meta": meta, "outbound": moved}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("orders", type=Path)
    parser.add_argument("--start", required=True, help="HH:MM 또는 초")
    parser.add_argument("--end", required=True, help="HH:MM 또는 초")
    parser.add_argument("--output", "-o", type=Path, help="기본: stdout")
    args = parser.parse_args(argv)
    try:
        data = json.load(open(args.orders, encoding="utf-8"))
        result = slice_orders(data, to_seconds(args.start), to_seconds(args.end))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    m = result["meta"]
    print(f"[slice] {m['orders_in_window']}/{m['orders_total']} orders in [{args.start}, {args.end}) → horizon_s={m['horizon_s']}",
          file=sys.stderr)
    out = open(args.output, "w", encoding="utf-8", newline="\n") if args.output else sys.stdout
    with out:
        json.dump(result, out, ensure_ascii=False, sort_keys=True, indent=2)
        out.write("\n")


if __name__ == "__main__":
    main()
