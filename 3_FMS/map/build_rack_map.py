# -*- coding: utf-8 -*-
# ============================================================
# 랙 → 통로 버퍼 매핑표 생성 (S15P21A106-156)
#
# WMS 주문의 rack_id("A2")를 시뮬 픽업 지점 aisle_buf[i] 로 바꾸는 표. 규칙:
#   랙 → 존(zone_id) → 존의 facility 좌표(x, y m) → stations.json aisle_buf 중 **같은 좌표**의 인덱스.
# 백엔드는 존 좌표를 그 존이 쓰는 통로 버퍼 스테이션 위치로 넣었다(2026-09-08 확인: 22개 전부 일치).
# 최근접 계산은 하지 않는다 — 하나라도 안 맞으면 실패시켜 마스터·맵이 어긋난 것을 드러낸다.
# 2026-08-31 계약 검토 §3-1 의 "랙 번호 1~3 남쪽 / 4~6 북쪽" 초안은 이 데이터로 대체한다(docs/맵_충전존.md).
#
# 입력: ../order_gen/master/santafactory_sample.json (extract_master.py 산출물), stations.json (이 폴더)
# 출력: rack_buffers.json — {"rule", "source", "zones": {zone_id: idx}, "racks": {"A1": idx, ...}}
# 사용: python build_rack_map.py            (마스터·시드가 바뀌면 다시 실행)
# ============================================================
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
MASTER = os.path.join(HERE, "..", "order_gen", "master", "santafactory_sample.json")
STATIONS = os.path.join(HERE, "stations.json")
OUT = os.path.join(HERE, "rack_buffers.json")


def build(master, stations):
    aisle_buf = [(round(x, 3), round(y, 3)) for x, y in stations["aisle_buf"]]
    if len(set(aisle_buf)) != len(aisle_buf):
        raise ValueError("aisle_buf 좌표 중복")
    coord_idx = {xy: i for i, xy in enumerate(aisle_buf)}
    facility = {f["facility_id"]: (round(f["x"], 3), round(f["y"], 3)) for f in master["facilities"]}
    zones = {}
    for z in master["zones"]:
        xy = facility.get(z["facility_id"])
        if xy is None:
            raise ValueError(f"zone {z['zone_id']}: facility {z['facility_id']} 없음")
        if xy not in coord_idx:
            raise ValueError(f"zone {z['zone_id']}: 좌표 {xy} 와 같은 aisle_buf 없음 — 마스터·맵 불일치")
        zones[z["zone_id"]] = coord_idx[xy]
    racks = {}
    for r in master["racks"]:
        if r["zone_id"] not in zones:
            raise ValueError(f"rack {r['field']}: zone {r['zone_id']} 없음")
        if r["field"] in racks:
            raise ValueError(f"rack field 중복: {r['field']}")
        racks[r["field"]] = zones[r["zone_id"]]
    return zones, racks


def main():
    master = json.load(open(MASTER, encoding="utf-8"))
    stations = json.load(open(STATIONS, encoding="utf-8"))
    zones, racks = build(master, stations)
    # 자기 검사: 존 22 ↔ 버퍼 22 일대일, 랙 132, 버퍼마다 랙 6개
    n_buf = len(stations["aisle_buf"])
    assert len(zones) == n_buf and sorted(zones.values()) == list(range(n_buf)), "존 ↔ 버퍼 가 일대일이 아님"
    per_buf = Counter(racks.values())
    assert len(racks) == len(master["racks"]) and set(per_buf.values()) == {len(master["racks"]) // n_buf}, \
        f"버퍼별 랙 수 불균일: {dict(per_buf)}"
    out = {
        "rule": "rack → zone → facility(x,y) == stations.json aisle_buf[i] (정확 일치, 최근접 아님)",
        "source": {"master": "order_gen/master/santafactory_sample.json", "stations": "map/stations.json"},
        "zones": {str(k): v for k, v in sorted(zones.items())},
        "racks": dict(sorted(racks.items())),
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"rack_buffers.json: 존 {len(zones)} / 랙 {len(racks)} / 버퍼 {n_buf} (버퍼당 랙 {len(racks) // n_buf})")


if __name__ == "__main__":
    sys.exit(main())
