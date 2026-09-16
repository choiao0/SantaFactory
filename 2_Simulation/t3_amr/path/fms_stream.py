# -*- coding: utf-8 -*-
"""FMS 배정표를 그대로 읽는 주문 스트림 (S15P21A106-224).

무엇을 맞추나
-------------
FMS 재현 절차(2026-09-16)는 주문을 **결과로** 준다 —
`packing_assign_s{seed}.csv` 6,000행에 「언제 · 어느 버퍼에서 · 어느 포장대로」
가 다 들어 있다.

    order_id, task_id, frm_name, to_name, created_tick
    0,        1,       aisle_buf[2], packing[2], 0

그래서 우리는 **규칙을 재현할 필요가 없다.** `lifelong.OrderStream` 을 이것으로
갈아끼우면 태스크 생성이 비트 단위로 같아진다.

    태스크 생성   언제 · 어느 버퍼 · 어느 포장대    <- 이 파일이 맞춘다
    배차          그 태스크를 어느 로봇이 가져가나   <- `dispatch.py` (이미 FMS 이식본)

포장대는 FMS 가 **배차 시점**에 정하는 값인데, 파일로 고정하면 우리 배차기가
못 고른다. 그게 맞다 — 이동 수요가 같아야 비교가 선다.

★ 인덱스 함정
-------------
`aisle_buf[2]` 를 `cells_by_cat["aisle_buf"][2]` 로 읽으면 **조용히 틀린다.**
`pibt_scene.station_cells()` 는 항목을 **버릴 수 있다** — 격자 밖, 못 서는 칸,
그리고 `(r,c) not in keep` 로 중복 제거까지 한다. 하나라도 빠지면 그 뒤 인덱스가
전부 밀린다.

그래서 **원본 `stations.json` 의 인덱스에서 직접 변환**한다. 그리고 두 경로가
같은 칸을 내는지 `verify()` 가 확인한다.

쓰는 법
-------
    from fms_stream import FileOrderStream
    stream = FileOrderStream(csv_path, geom, free, map_dir, horizon)

자체 점검:
    source paths.sh
    SEED=103 python path/fms_stream.py
"""
import collections
import csv
import os
import re
import sys

IDX = re.compile(r"^([A-Za-z_]+)\[(\d+)\]$")
# FMS 재현 절차 §1-1 ①. 속도 0.9 · MOVE_TICKS 4.
DT = 1.0 / (float(os.environ.get("SPEED", "0.9")) * 4)


class FileOrderStream(object):
    """`lifelong.OrderStream` 과 같은 자리에 꽂힌다.

    커널이 쓰는 것은 `arrivals(t)` · `n_task` · `windows` · `order_end` 넷이다.
    """

    def __init__(self, csv_path, geom, free, map_dir, horizon,
                 order_end=None, verbose=True):
        import pibt_scene as PS

        self.path = csv_path
        self.horizon = int(horizon)
        self.order_end = None if order_end is None else max(0, int(order_end))
        self.n_task = 0
        # 교대 창은 파일이 정한다. 커널이 `info` 에만 쓰므로 한 칸으로 둔다.
        self.windows = [("out", 0, self.horizon)]

        self._pts = PS.load_stations(map_dir)
        self._geom, self._free, self._PS = geom, free, PS
        self._cache = {}

        self._by_tick = collections.defaultdict(list)
        self.skipped_late = 0        # horizon 밖이라 버린 것
        self.skipped_bad = []        # 칸을 못 찾은 것
        self.total = 0

        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self.total += 1
                t = int(row["created_tick"])
                if t >= self.horizon:
                    self.skipped_late += 1
                    continue
                frm = self._resolve(row["frm_name"])
                to = self._resolve(row["to_name"])
                if frm is None or to is None:
                    self.skipped_bad.append((row["frm_name"], row["to_name"]))
                    continue
                self._by_tick[t].append(
                    {"kind": "out", "frm": frm, "to": to, "born": t})

        self.loaded = sum(len(v) for v in self._by_tick.values())
        if verbose:
            print(f"[fms_stream] {os.path.basename(csv_path)} · "
                  f"{self.total:,}행 -> {self.loaded:,}건 적재 "
                  f"(horizon {self.horizon:,}틱)")
            if self.skipped_late:
                print(f"[fms_stream]   horizon 밖이라 뺌 {self.skipped_late:,}건")
            if self.skipped_bad:
                print(f"[fms_stream]   ★ 칸을 못 찾음 {len(self.skipped_bad)}건 — "
                      f"예: {self.skipped_bad[:3]}")

    # ── 이름 -> 칸 ────────────────────────────────────────────────────────
    def _resolve(self, name):
        """`aisle_buf[2]` -> (r, c). **원본 인덱스에서** 변환한다.

        `station_cells()` 로 만든 목록을 인덱싱하면 안 된다 — 거기서는 못 서는
        칸과 중복이 빠져 인덱스가 밀린다.
        """
        if name in self._cache:
            return self._cache[name]
        m = IDX.match(name.strip())
        got = None
        if m:
            cat, i = m.group(1), int(m.group(2))
            pts = self._pts.get(cat)
            if isinstance(pts, list) and 0 <= i < len(pts):
                p = pts[i]
                if isinstance(p, (list, tuple)) and len(p) == 2:
                    got = self._cell(p)
        self._cache[name] = got
        return got

    def _cell(self, p):
        """`station_cells` 와 **같은 규칙**으로 칸을 정한다."""
        PS, free = self._PS, self._free
        R, C = free.shape
        r, c = PS._cell_of(self._geom, p[0], p[1])
        if not (0 <= r < R and 0 <= c < C):
            return None
        if not free[r, c]:
            rc = PS._nearest_free(free, (r, c), set())
            if rc is None:
                return None
            r, c = rc
        if PS._first_valid_heading(free, (r, c)) is None:
            return None
        return (r, c)

    # ── 커널이 부르는 것 ──────────────────────────────────────────────────
    def arrivals(self, t):
        if self.order_end is not None and t >= self.order_end:
            return []
        out = self._by_tick.get(t, ())
        self.n_task += len(out)
        return list(out)

    # ── ★ 인덱스가 밀리지 않았나 ─────────────────────────────────────────
    def verify(self):
        """`station_cells()` 로 인덱싱했다면 같은 칸이 나왔을지 본다.

        다르면 **그 방식으로 읽던 코드가 조용히 틀린다**는 뜻이다. 우리는
        원본 인덱스를 쓰므로 영향은 없지만, 차이 자체를 알아야 한다.
        """
        cells = self._PS.station_cells(self._free, self._geom,
                                       os.environ["MAP"])
        bad = []
        for cat, pts in self._pts.items():
            if not isinstance(pts, list):
                continue
            kept = cells.get(cat, [])
            if len(kept) != len(pts):
                bad.append((cat, len(pts), len(kept)))
        return bad


def _main():
    sys.path.insert(0, os.path.join(os.environ["W"], "path"))
    import pibt_scene as PS

    sd = os.environ.get("SEED", "103")
    pitch = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.0")))
    n = int(os.environ.get("N", "24"))
    horizon = int(os.environ.get("HORIZON", "77760"))
    csv_path = os.environ.get(
        "ASSIGN", os.path.join(os.environ["W"], "tools", "_orders",
                               f"packing_assign_s{sd}.csv"))

    geom, free, _starts, _goals = PS.setup_lifelong(
        os.environ["MAP"], n, pitch, int(sd), verbose=False)
    st = FileOrderStream(csv_path, geom, free, os.environ["MAP"], horizon)

    print(f"\n── 인덱스 검사 ──")
    bad = st.verify()
    if bad:
        print(f"   ★ `station_cells()` 가 항목을 버린 카테고리가 있다 —")
        for cat, raw, kept in bad:
            print(f"     {cat}: 원본 {raw} -> {kept}  (인덱스가 밀린다)")
        print(f"   우리는 **원본 인덱스**에서 변환하므로 영향은 없다.")
    else:
        print(f"   두 경로의 항목 수가 같다 — 인덱스가 안 밀린다")

    print(f"\n── 적재 결과 ──")
    ticks = sorted(st._by_tick)
    print(f"   틱 {ticks[0]:,} ~ {ticks[-1]:,} · 서로 다른 틱 {len(ticks):,}개")
    frm = collections.Counter(t["frm"] for v in st._by_tick.values() for t in v)
    to = collections.Counter(t["to"] for v in st._by_tick.values() for t in v)
    print(f"   출발 칸 {len(frm)}종 · 도착 칸 {len(to)}종")
    print(f"   도착 칸 분포 {dict(sorted(to.items()))}")

    win = round(1800 / DT)
    early = sum(len(v) for t, v in st._by_tick.items() if t < win)
    print(f"\n   첫 30분(<{win:,}틱) {early:,}건 "
          f"({early / max(st.loaded, 1) * 100:.1f} %)   기대 ~38 %")

    print(f"\n── arrivals() 동작 ──")
    for t in ticks[:3]:
        print(f"   t={t:<6} {st.arrivals(t)}")
    print(f"   n_task 누적 {st.n_task}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
