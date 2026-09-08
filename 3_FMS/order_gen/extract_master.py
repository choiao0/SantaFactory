#!/usr/bin/env python3
"""백엔드 시드 SQL(Flyway db/seed/R__seed_demo.sql)의 INSERT 를 파싱해 생성기 마스터 JSON 을 만든다.

생성기가 쓰는 필드만 남긴다: stores(store_id, zone_id, outbound_count), products(product_id, store_id, rack_id),
racks(rack_id, zone_id, field), zones(zone_id, warehouse_id, facility_id), facilities(facility_id, type, x, y).
좌표는 존이 쓰는 통로 버퍼 스테이션 위치이며 랙 → 버퍼 매핑(map/build_rack_map.py)의 입력이다. 이름·가격은 넣지 않는다.

    python extract_master.py ../../4_Web/SantaFactoryBE/src/main/resources/db/seed/R__seed_demo.sql -o master/santafactory_sample.json
"""

import argparse
import json
import re
import sys
from pathlib import Path


def _block(sql, table):
    parts = sql.split(f"INSERT INTO {table}")
    if len(parts) < 2:
        raise ValueError(f"INSERT INTO {table} 가 없음")
    return parts[1].split(";")[0]


def extract_master(sql_path):
    sql = Path(sql_path).read_text(encoding="utf-8")
    stores = [{"store_id": int(a), "zone_id": int(b), "outbound_count": int(c)}
              for a, b, c in re.findall(r"\((\d+)\s*,\s*(\d+)\s*,\s*'[^']*'\s*,\s*'[^']*'\s*,\s*(\d+)\)", _block(sql, "stores"))]
    racks = [{"rack_id": int(a), "zone_id": int(b), "field": f}
             for a, b, f in re.findall(r"\((\d+),(\d+),'([A-Z]+\d+)'\)", _block(sql, "rack"))]
    products = [{"product_id": int(a), "store_id": int(b), "rack_id": int(c)}
                for a, b, c in re.findall(r"\((\d+),(\d+),(\d+),", _block(sql, "products"))]
    zones = [{"zone_id": int(a), "warehouse_id": int(b), "facility_id": int(c)}
             for a, b, c in re.findall(r"\((\d+)\s*,(\d+),(\d+)\s*,", _block(sql, "zones"))]
    # 존 좌표(m). 랙 → 시뮬 통로 버퍼 매핑(map/build_rack_map.py)이 stations.json 의 aisle_buf 좌표와 대조한다.
    facilities = [{"facility_id": int(a), "type": t, "x": float(x), "y": float(y)}
                  for a, t, x, y in re.findall(r"\((\d+)\s*,\s*'([A-Z_]+)'\s*,\s*([\d.]+)\s*,\s*([\d.]+)\)", _block(sql, "facility"))]
    if not (stores and racks and products and zones and facilities):
        raise ValueError("파싱 결과가 비어 있음 — SQL 형식이 바뀌었는지 확인")
    return {"stores": stores, "racks": racks, "products": products, "zones": zones, "facilities": facilities}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sql", type=Path, help="R__seed_demo.sql 경로 (4_Web/SantaFactoryBE/src/main/resources/db/seed/)")
    parser.add_argument("--output", "-o", type=Path, help="저장할 마스터 JSON (기본: stdout)")
    args = parser.parse_args(argv)
    try:
        master = extract_master(args.sql)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    destination = open(args.output, "w", encoding="utf-8", newline="\n") if args.output else sys.stdout
    with destination:
        json.dump(master, destination, ensure_ascii=False, sort_keys=True, indent=2)
        destination.write("\n")


if __name__ == "__main__":
    main()
