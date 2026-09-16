# -*- coding: utf-8 -*-
"""FMS 주문 파일 점검표 (S15P21A106-224).

FMS 「시나리오 재현 절차」(2026-09-16) §7 의 1~4 를 기계로 확인한다.
순서대로 맞아야 그 아래가 의미를 갖는다.

    1  주문 파일 sha256 일치
    2  파싱 결과: 주문 6,000 · 토트 6,000  (주문 1건 = 토트 1개)
    3  도착 분포: 첫 30분(0~1800 s)에 2,250건 안팎 = 38 %
    4  dt = 0.277778 s · 6h = 77,760틱 · 포화 창 6,480~38,880틱

그리고 **배정표**(`packing_assign_s*.csv`)를 같이 본다. FMS 가 포장대 배정
결과를 통째로 줬으므로 우리가 규칙을 추측해 재현할 필요가 없다 — 읽으면 된다.
그 표의 `frm_name`·`to_name` 이 우리 `stations.json` 인덱스 범위에 드는지가
마지막 관문이다.

쓰는 법
-------
    source paths.sh
    python tools/fms_orders_check.py                 # 시드 전부
    SEED=103 python tools/fms_orders_check.py
"""
import collections
import csv
import hashlib
import json
import os
import re
import sys

W = os.environ["W"]
ORD = os.environ.get("ORDERS_DIR", os.path.join(W, "tools", "_orders"))
DT = 1.0 / (float(os.environ.get("SPEED", "0.9")) * 4)
SEEDS = [s for s in os.environ.get("SEED", "101,103,104").split(",") if s]

# FMS 재현 절차 §1-1 이 준 값 (앞 16자)
WANT = {
    "101": "121c2c13aeb89bca",
    "103": "08d844b745b8a8cf",
    "104": "60e59afda40b4c22",
}
IDX = re.compile(r"\[(\d+)\]")


def sha16(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()[:16]


def main():
    st = json.load(open(os.path.join(os.environ["MAP"], "stations.json")))
    print(f"[fms_orders_check] {ORD}")
    print(f"   dt {DT:.6f}s · 6h {round(21600 / DT):,}틱 · "
          f"포화 창 {round(1800 / DT):,}~{round(10800 / DT):,}틱")
    print(f"   우리 stations: aisle_buf {len(st['aisle_buf'])} · "
          f"packing {len(st['packing'])} · consol {len(st['consol'])}")

    ok_all = True
    for sd in SEEDS:
        f_ord = os.path.join(ORD, f"orders6000_s{sd}_cap10.json")
        f_pack = os.path.join(ORD, f"packing_assign_s{sd}.csv")
        print(f"\n══ 시드 {sd} ══")
        if not os.path.isfile(f_ord):
            print(f"   ★ 없다: {f_ord}")
            ok_all = False
            continue

        # ── □1 sha256 ────────────────────────────────────────────────────
        got = sha16(f_ord)
        want = WANT.get(sd)
        hit = (want is None) or (got == want)
        ok_all &= hit
        print(f"   □1 sha256 {got}"
              + (f"  기대 {want}  {'★ 일치' if hit else '☠ 불일치'}"
                 if want else "  (기대값 없음)"))

        d = json.load(open(f_ord))
        ob = d["outbound"]
        meta = d.get("meta", {})
        lines = sum(len(o["lines"]) for o in ob)
        units = sum(l.get("qty", 0) for o in ob for l in o["lines"])
        print(f"      meta: orders {meta.get('orders')} · lines {meta.get('lines')}"
              f" · units {meta.get('units')} · cap {meta.get('order_qty_cap')}"
              f" · release {meta.get('release')!r}")
        print(f"      실제: outbound {len(ob):,} · lines {lines:,} · units {units:,}")

        # ── □3 도착 분포 ─────────────────────────────────────────────────
        ar = [o["ordered_at_s"] for o in ob]
        n30 = sum(1 for s in ar if s < 1800)
        pct = n30 / len(ob) * 100
        good3 = 30.0 <= pct <= 46.0
        ok_all &= good3
        print(f"   □3 도착 {min(ar)}~{max(ar)}s · 첫 30분 {n30:,}건 "
              f"({pct:.1f} %)  {'★' if good3 else '☠'} 기대 ~2,250 · 38 %")

        # ── □2 + 배정표 ──────────────────────────────────────────────────
        if not os.path.isfile(f_pack):
            print(f"   □2 배정표 없다: {f_pack}")
            ok_all = False
            continue
        rows = list(csv.DictReader(open(f_pack)))
        good2 = len(rows) == len(ob)
        ok_all &= good2
        print(f"   □2 주문 {len(ob):,} · 토트 {len(rows):,}  "
              f"{'★ 1:1' if good2 else '☠ 안 맞는다'}")

        frm = collections.Counter(r["frm_name"].split("[")[0] for r in rows)
        to = collections.Counter(r["to_name"].split("[")[0] for r in rows)
        print(f"      frm {dict(frm)}   to {dict(to)}")
        pk = collections.Counter(r["to_name"] for r in rows)
        print(f"      포장대 분포 {dict(sorted(pk.items()))}")

        ct = [int(r["created_tick"]) for r in rows]
        print(f"      created_tick {min(ct):,}~{max(ct):,}  (6h = 77,760)")

        # ── ★ 조인 키와 틱 규칙 ──────────────────────────────────────────
        #   CSV `order_id` 는 **0부터**, JSON `order_id` 는 **1부터**다.
        #   맞물리는 키는 CSV 의 `task_id` 다. `order_id` 로 이으면 한 칸씩
        #   밀려서 「틱이 30 % 어긋난다」로 보인다 — 2026-09-16 에 실제로
        #   그렇게 읽었다.
        tick = {int(r["task_id"]): int(r["created_tick"]) for r in rows}
        n_ok = sum(1 for o in ob
                   if tick.get(o["order_id"]) == int(o["ordered_at_s"] / DT))
        wrong = sum(1 for o in ob if tick.get(o["order_id"]) is None)
        good1 = n_ok == len(ob)
        ok_all &= good1
        print(f"   □1-② 도착 틱 = int(ordered_at_s / dt) · 조인 키 task_id")
        print(f"      일치 {n_ok:,}/{len(ob):,}  {'★' if good1 else '☠'}"
              + ("" if not wrong else f"   (조인 실패 {wrong:,})"))

        # ── ★ 한 주문이 버퍼 하나로만 가나 ───────────────────────────────
        #   문서 ③ 은 「같은 버퍼의 qty 를 합치고 ceil(합/10)」이라 한 주문이
        #   두 버퍼에 걸치면 토트가 둘이 된다. 그러면 1:1 이 깨진다.
        rb = json.load(open(os.path.join(os.environ["MAP"], "rack_buffers.json")))
        racks = rb.get("racks", rb)
        span, miss = collections.Counter(), set()
        for o in ob:
            z = set()
            for l in o["lines"]:
                rid = l["rack_id"]
                (z.add(racks[rid]) if rid in racks else miss.add(rid))
            span[len(z)] += 1
        good5 = set(span) == {1}
        ok_all &= good5 and not miss
        print(f"   □3-② 한 주문이 걸치는 버퍼 수 {dict(sorted(span.items()))}"
              f"  {'★ 전부 하나 -> 1:1 성립' if good5 else '☠ 갈라진다'}")
        if miss:
            print(f"      ☠ rack_buffers 에 없는 rack_id {len(miss)}종: "
                  f"{sorted(miss)[:6]}")

        # meta 의 units 는 파일의 qty 합과 다르다 — cap 적용 전 값으로 보인다.
        if meta.get("units") and abs(meta["units"] - units) > 1:
            print(f"      ※ meta.units {meta['units']:,} != 파일 qty 합 "
                  f"{units:,} — cap 적용 전 값으로 보인다 (확인 필요)")

        # ── ★ 우리 stations 에 들어맞나 ──────────────────────────────────
        bad = []
        for r in rows:
            for col, cat in (("frm_name", None), ("to_name", None)):
                name = r[col]
                key = name.split("[")[0]
                m = IDX.search(name)
                pool = st.get(key)
                if pool is None:
                    bad.append((name, "없는 카테고리"))
                elif not m or not (0 <= int(m.group(1)) < len(pool)):
                    bad.append((name, f"범위 밖 (우리 {len(pool)}개)"))
        ok_all &= not bad
        if bad:
            print(f"   ☠ stations 에 안 맞는 이름 {len(bad)}건 — "
                  f"예: {bad[:3]}")
        else:
            print(f"   ★ `frm_name`·`to_name` 이 전부 우리 stations 범위 안이다")

    print(f"\n══ {'전부 통과 — §7 의 1~4 가 맞는다' if ok_all else '☠ 안 맞는 항목이 있다'} ══")
    if ok_all:
        print("   다음: 이 배정표를 그대로 읽는 OrderStream 을 만든다.")
        print("   포장대 규칙을 추측해 재현할 필요가 없다 — 결과가 주어졌다.")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
