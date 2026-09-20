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

# ★★ 틱은 **pitch 에 걸린다.** 이걸 안 보면 1.0 vs 1.2 비교가 통째로 망가진다.
#
#     dt = pitch / (v_plan x MOVE_TICKS)
#         pitch 1.0 -> 0.27778 s
#         pitch 1.2 -> 0.33333 s
#
#   `packing_assign` 의 `created_tick` 은 **FMS 격자(1.0 m)** 에서 만든 값이라
#   0.27778 s 짜리 틱이다. 그걸 1.2 판에 **그대로** 넣으면 같은 틱 번호가
#   0.33333 s 를 뜻하게 되어, 도착 시각이 통째로 **1.2배 늘어난다** —
#   1.2 판이 같은 6시간 동안 주문을 덜 받는다. 그 상태로 포화 처리량을 맞대면
#   1.2 가 유리한 쪽으로 기울고, 원인은 지표에 안 보인다.
#
#   그래서 **초로 한 번 돌린다**: 파일 틱 -> 초 -> 우리 틱.
#       tick_ours = round(tick_file * DT_FILE / DT_OURS) = round(tick_file / pitch)
#   pitch 1.0 이면 배율이 정확히 1.0 이라 **비트 단위로 같다** (아래 검증).
#
#   `DT` 는 옛 이름 그대로 둔다 — 파일 쪽 dt 다.
DT = float(os.environ.get("FMS_FILE_DT", "")
           or 1.0 / (float(os.environ.get("SPEED", "0.9")) * 4))


def our_dt(geom):
    """우리 격자의 틱 길이 [s]. `isaac_drive` 의 `tick_s` 와 **같은 식**이다.

    거기서는 `geom.pitch / (geom.v_max * MOVE_TICKS)` 로 쓴다
    (`isaac_drive.py:1762`). 두 벌로 두면 조용히 갈리므로 식을 옮겨 적는다.
    """
    from pibt_core import MOVE_TICKS
    return geom.pitch / (geom.v_max * MOVE_TICKS)

# 첫 30분 비율의 기대값과 허용폭 (FMS 재현 절차). 분포가 통째로 다른 파일을
# 물었는지 보는 거친 지표라 폭을 넉넉히 둔다 — 정밀도가 아니라 **자릿수**다.
EARLY_EXPECT = float(os.environ.get("FMS_EARLY_PCT", "38"))
EARLY_TOL = float(os.environ.get("FMS_EARLY_TOL", "4"))


def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _orders_json_for(csv_path):
    """`packing_assign_s103.csv` 의 짝이 되는 주문 JSON 을 찾는다.

    `FMS_ORDERS_JSON` 이 있으면 그것. 없으면 같은 폴더에서
    `orders*_s{seed}_*.json` 을 찾는다.

    ★ 여럿이면 **고르지 않고 일치를 확인한다.** 실제로 시드마다 `cap10` 과
      `cap24` 두 벌이 있는데, 둘은 수량 상한만 다르고 ②④ 가 쓰는 값
      (주문 집합 · 주문별 랙)은 **완전히 같다** (실측 s103: 6,000/6,000 ·
      랙 집합이 다른 주문 0건). 그러니 아무거나 써도 되는데, **그걸 확인하고**
      쓰는 것과 **가정하고** 쓰는 것은 다르다. 다르면 거기서 끊는다.

      이걸 「후보가 둘이라 건너뜀」으로 두었더니 제일 중요한 ④ 가 매번
      안 돌았다 (2026-09-17).
    """
    import glob
    import json
    env = os.environ.get("FMS_ORDERS_JSON", "").strip()
    if env:
        return env, "FMS_ORDERS_JSON", None
    m = re.search(r"_s(\d+)", os.path.basename(csv_path))
    if not m:
        return None, "시드를 파일명에서 못 읽었다", None
    d = os.path.dirname(os.path.abspath(csv_path))
    hit = sorted(glob.glob(os.path.join(d, f"orders*_s{m.group(1)}_*.json")))
    if not hit:
        return None, f"orders*_s{m.group(1)}_*.json 이 없다", None
    if len(hit) == 1:
        return hit[0], "자동", None

    def key(p):
        with open(p, encoding="utf-8") as f:
            j = json.load(f)
        return {o["order_id"]: tuple(sorted({l.get("rack_id")
                                             for l in o.get("lines", ())}))
                for o in j.get("outbound", ())}
    base = key(hit[0])
    for p in hit[1:]:
        if key(p) != base:
            return None, (f"후보 {len(hit)}개가 **서로 다르다** — "
                          f"`FMS_ORDERS_JSON` 으로 지정할 것: "
                          + ", ".join(os.path.basename(x) for x in hit)), None
    return hit[0], "자동", (f"후보 {len(hit)}개가 주문 집합·주문별 랙에서 "
                            f"일치함을 확인하고 첫 번째를 씀 ("
                            + ", ".join(os.path.basename(x) for x in hit) + ")")


class FileOrderStream(object):
    """`lifelong.OrderStream` 과 같은 자리에 꽂힌다.

    커널이 쓰는 것은 `arrivals(t)` · `n_task` · `windows` · `order_end` 넷이다.
    """

    def __init__(self, csv_path, geom, free, map_dir, horizon,
                 order_end=None, verbose=True):
        import pibt_scene as PS

        self.path = csv_path
        self.sha256 = sha256(csv_path)
        self.horizon = int(horizon)
        self.order_end = None if order_end is None else max(0, int(order_end))
        self.n_task = 0
        # 교대 창은 파일이 정한다. 커널이 `info` 에만 쓰므로 한 칸으로 둔다.
        self.windows = [("out", 0, self.horizon)]

        self._pts = PS.load_stations(map_dir)
        self._geom, self._free, self._PS = geom, free, PS
        self._map = map_dir
        self._cache = {}

        self._by_tick = collections.defaultdict(list)
        self.skipped_late = 0        # horizon 밖이라 버린 것
        self.skipped_bad = []        # 칸을 못 찾은 것
        self.total = 0

        # ★ 도착 분포는 **파일 전체**로 센다 — horizon 과 무관하게 (2026-09-17).
        #   `loaded`(horizon 안)로 재면 horizon 이 30분보다 짧을 때 전부가
        #   「첫 30분」이라 100 % 가 나오고, 단언 ③ 이 거짓 경보를 낸다.
        #   실제로 `run_lifelong(horizon=1260)` 에서 그렇게 터졌다.
        #   이 값은 「어떤 파일인가」를 묻는 것이지 「우리가 얼마나 쓰나」가 아니다.
        # 첫 30분은 **파일 틱**으로 잰다 (파일의 성질이므로 파일 dt 로).
        self._early_win = round(1800.0 / DT)
        self._early_all = 0

        # ★ 파일 틱 -> 우리 틱 배율. pitch 1.0 이면 정확히 1.0 이다.
        self.dt_file = DT
        self.dt_ours = our_dt(geom)
        self.tick_scale = self.dt_file / self.dt_ours
        self.rescaled = abs(self.tick_scale - 1.0) > 1e-12

        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self.total += 1
                t_file = int(row["created_tick"])
                if t_file < self._early_win:
                    self._early_all += 1
                t = (t_file if not self.rescaled
                     else int(round(t_file * self.tick_scale)))
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

    # ── ★ 출처를 한 줄로 ─────────────────────────────────────────────────
    def provenance(self):
        """머리글에 찍을 한 줄. **이게 없어서 30분을 날렸다** (2026-09-17).

        주문이 파일에서 왔는지 시드에서 났는지 로그만 보고는 못 갈랐다.
        확인은 액션 수로도 된다 — 시드 생성이 416,714 라, 파일을 물면 반드시
        달라야 한다. 같으면 파일이 **안 걸린** 것이다.
        """
        scale = ("틱 그대로 (pitch 1.0)" if not self.rescaled else
                 f"★ 틱 환산 x{self.tick_scale:.5f} "
                 f"(파일 dt {self.dt_file:.5f}s -> 우리 dt {self.dt_ours:.5f}s)")
        return (f"파일 {os.path.basename(self.path)} · sha256 "
                f"{self.sha256[:12]}… · {self.loaded:,}건 "
                f"(전체 {self.total:,}행, horizon {self.horizon:,}틱) · {scale}")

    # ── ★ 로드 시 단언 넷 ────────────────────────────────────────────────
    def check(self, strict=True, verbose=True):
        """엉뚱한 파일·엉뚱한 매핑을 **포화 결과 전에** 잡는다.

        넷 다 「틀리면 포화 지표에서만 드러나고, 그때는 원인이 안 갈리는」
        종류다. 특히 ④ 가 그렇다 — 매핑이 밀리면 이동 수요가 통째로 달라지는데
        주행은 멀쩡히 돌고 처리량만 이상해진다.

            ① sha256          어느 파일인가. `FMS_SHA256` 을 주면 대조한다
            ② 주문 = 토트      CSV 행수 == JSON outbound == meta.orders
            ③ 첫 30분 비율     분포가 통째로 다른 파일인지 보는 거친 지표
            ④ frm 매핑        **우리가 rack_buffers 로 계산한 칸**이
                              CSV `frm_name` 과 같은가

        `strict` 면 실패에서 `RuntimeError`. `FMS_CHECK=warn` 으로 낮춘다.
        """
        import json
        bad, note = [], []

        # ① sha256
        want = os.environ.get("FMS_SHA256", "").strip()
        if want and want != self.sha256:
            bad.append(f"① sha256 불일치 — 기대 {want[:12]}… / 실제 "
                       f"{self.sha256[:12]}…")
        note.append(f"① sha256 {self.sha256[:16]}…"
                    + ("  (FMS_SHA256 과 일치)" if want else "  (대조값 없음)"))

        done = ["①"]
        jp, why, agreed = _orders_json_for(self.path)
        if agreed:
            note.append(f"   {agreed}")
        if jp is None:
            note.append(f"②④ **건너뜀** — {why}")
            self._report(note, bad, strict, verbose, done)
            return bad
        with open(jp, encoding="utf-8") as f:
            od = json.load(f)
        ob = od.get("outbound", [])
        meta = od.get("meta", {})

        # ② 주문 = 토트
        n_csv, n_json = self.total, len(ob)
        n_meta = int(meta.get("orders", -1))
        if not (n_csv == n_json == n_meta):
            bad.append(f"② 개수가 안 맞는다 — CSV {n_csv:,} · JSON {n_json:,} "
                       f"· meta.orders {n_meta:,}")
        done.append("②")
        note.append(f"② 주문 {n_csv:,} = 토트 {n_json:,} "
                    f"(meta.orders {n_meta:,})  · {os.path.basename(jp)} [{why}]")

        # ③ 첫 30분 비율 — **파일 전체** 기준 (horizon 과 무관)
        win, early = self._early_win, self._early_all
        pct = 100.0 * early / max(self.total, 1)
        if abs(pct - EARLY_EXPECT) > EARLY_TOL:
            bad.append(f"③ 첫 30분 {pct:.1f} % — 기대 {EARLY_EXPECT:.0f} "
                       f"± {EARLY_TOL:.0f}. 다른 파일이거나 틱 변환이 틀렸다")
        done.append("③")
        note.append(f"③ 첫 30분(<{win:,}틱) {early:,}/{self.total:,}행 "
                    f"= {pct:.1f} % (기대 {EARLY_EXPECT:.0f} ± {EARLY_TOL:.0f})"
                    + ("" if self.horizon >= win else
                       f"  ※ horizon {self.horizon:,} < {win:,} 이라 이 판은 "
                       f"파일의 앞부분만 쓴다"))

        # ④ ★ frm 매핑 — 우리가 계산한 값이 CSV 와 같은가
        rbp = os.path.join(self._map, "rack_buffers.json")
        if not os.path.exists(rbp):
            note.append(f"④ rack_buffers.json 이 없어 건너뜀 ({rbp})")
        else:
            with open(rbp, encoding="utf-8") as f:
                racks = json.load(f).get("racks", {})
            by_oid = {o.get("order_id"): o for o in ob}
            miss, mism, split = 0, [], 0
            with open(self.path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    o = by_oid.get(int(row["task_id"]))
                    if o is None:
                        miss += 1
                        continue
                    idx = {racks.get(l.get("rack_id")) for l in o.get("lines", ())}
                    idx.discard(None)
                    if len(idx) != 1:
                        split += 1
                        continue
                    mine = f"aisle_buf[{idx.pop()}]"
                    if mine != row["frm_name"].strip():
                        mism.append((row["task_id"], mine, row["frm_name"]))
            if miss:
                bad.append(f"④ task_id 가 JSON order_id 에 없는 행 {miss:,}건 "
                           f"— 조인 키가 틀렸다")
            if mism:
                bad.append(f"④ ★ frm 매핑이 다른 행 {len(mism):,}건 — "
                           f"예: {mism[:3]}")
            done.append("④")
            note.append(f"④ frm 매핑 대조 {n_csv:,}행 · 불일치 {len(mism):,} · "
                        f"조인 실패 {miss:,} · 한 주문이 여러 버퍼 {split:,}")

        self._report(note, bad, strict, verbose, done)
        return bad

    @staticmethod
    def _report(note, bad, strict, verbose, done=()):
        # ★ **돈 것만 통과라고 말한다** (2026-09-17). 처음에는 실패가 없으면
        #   무조건 「단언 넷 통과」를 찍었는데, 그때 ②④ 는 건너뛰고 있었다.
        #   오늘만 세 번째로 나온 같은 종류의 버그다 — 거짓말하는 진단.
        ALL = ("①", "②", "③", "④")
        miss = [k for k in ALL if k not in tuple(done)]
        if verbose:
            for ln in note:
                print(f"[fms_stream]   {ln}")
        if not bad:
            if verbose:
                if miss:
                    print(f"[fms_stream]   ~ {len(done)}/4 통과 · "
                          f"**{''.join(miss)} 는 안 돌았다** — 위 사유를 볼 것")
                else:
                    print("[fms_stream]   ★ 단언 넷 전부 통과")
            return
        msg = "★ 주문 파일 단언 실패:\n  " + "\n  ".join(bad)
        if strict and os.environ.get("FMS_CHECK", "") not in ("warn", "0"):
            raise RuntimeError(
                msg + "\n  (`FMS_CHECK=warn` 으로 낮출 수 있다 — 다만 "
                      "틀린 채로 돌면 포화 지표에서만 드러난다)")
        print("[fms_stream] " + msg, file=sys.stderr)

    # ── ★ 인덱스가 밀리지 않았나 ─────────────────────────────────────────
    def verify(self):
        """`cells_by_cat[cat][i]` 가 `stations.json` 의 i 번째와 같은 칸인가.

        다르면 **그 방식으로 읽던 코드가 조용히 틀린다**는 뜻이다. 우리는
        원본 인덱스를 쓰므로 영향은 없지만, 차이 자체를 알아야 한다.

        ★ 길이만 비교하면 안 된다. `station_cells` 는 애초에 **점 두 개짜리
          항목만** 본다 -- `charge_zone` 은 사각형 하나(`{id,x0,x1,y0,y1}`)라
          당연히 빠지고, 충전존 칸은 `charge_zone_cells` 가 따로 만든다.
          길이로 재면 그걸 매번 「인덱스가 밀린다」로 외친다. 한 번 울고 나면
          다음에 진짜 밀렸을 때 아무도 안 읽는다.

        그래서 **점 항목만 골라 인덱스별로 칸을 맞대 본다.**
        """
        cells = self._PS.station_cells(self._free, self._geom, self._map)
        bad = []
        for cat, pts in self._pts.items():
            if not isinstance(pts, list):
                continue
            pts = [p for p in pts
                   if isinstance(p, (list, tuple)) and len(p) == 2]
            if not pts:
                continue
            kept = cells.get(cat, [])
            for i, p in enumerate(pts):
                mine = self._cell(p)
                theirs = kept[i] if i < len(kept) else None
                if mine != theirs:
                    bad.append((cat, i, mine, theirs))
        return bad


def from_env(free, horizon, geom=None, map_dir=None, order_end=None):
    """`FMS_ASSIGN` 이 있으면 스트림을, 없으면 `None` 을 돌려준다.

    ★ 왜 여기인가 (2026-09-17). `pibt_scene` 에만 꽂으면
      `plan_scale`·`soft_probe`·`adg_edge_audit` 이 **전부 안 탄다.** 셋 다
      `lifelong.run_lifelong` 을 직접 부르기 때문이다. 그래서 공통 진입점인
      `run_lifelong` 이 이 함수를 부르고, 도구는 아무것도 안 고쳐도 따라온다.

      그리고 이 배치가 옛 함정을 **없앤다** — 예전에는 계획만 배정표로 서고
      주행은 난수 스트림으로 돌았다 (주행이 `live_pibt` 에서 다시 계획한다).
      이제 둘 다 `run_lifelong` 을 지나므로 갈릴 자리가 없다.

    `lifelong.py` 에 FMS 파일 형식이 섞이지 않게, 형식을 아는 코드는 전부
    이쪽에 둔다 (`run_lifelong` 독스트링의 약속).
    """
    path = os.environ.get("FMS_ASSIGN", "").strip()
    if not path:
        return None
    if not os.path.exists(path):
        raise RuntimeError(f"★ FMS_ASSIGN 이 가리키는 파일이 없다: {path}")
    if map_dir is None:
        map_dir = os.environ.get("MAP", "")
    if not map_dir:
        raise RuntimeError("★ FMS_ASSIGN 을 쓰려면 `MAP` 이 필요하다 "
                           "(source paths.sh)")
    if geom is None:
        import pibt_scene as PS
        geom = PS.make_geom(float(os.environ.get("PIBT_PITCH", "1.0")))
    st = FileOrderStream(path, geom, free, map_dir, horizon,
                         order_end=order_end)
    st.check(strict=True)
    return st


def _main():
    sys.path.insert(0, os.path.join(os.environ["W"], "path"))
    import pibt_scene as PS

    sd = os.environ.get("SEED", "103")
    pitch = float(os.environ.get("PITCH", os.environ.get("PIBT_PITCH", "1.0")))
    n = int(os.environ.get("N", "24"))
    horizon = int(os.environ.get("HORIZON", "77760"))
    # ★ 이름이 `FMS_ASSIGN` 이다. 옛 이름 `ASSIGN` 은 `pibt_scene.py --orders` 의
    #   기본값이기도 해서, 한 번 export 하고 같은 셸에서 `run_record.sh` 를
    #   돌리면 **계획만** 배정표로 서고 주행은 난수 스트림으로 돌았다
    #   (주행은 `live_pibt` 가 다시 계획한다). 이름을 겹치지 않게 옮겼다.
    #
    #   ★★ 그리고 `from_env()` 가 `run_lifelong` 에서 같은 이름을 읽으므로
    #     이제 계획과 주행이 **같은 자리**를 지난다 — 갈릴 데가 없어졌다.
    csv_path = os.environ.get(
        "FMS_ASSIGN", os.path.join(os.environ["W"], "tools", "_orders",
                                   f"packing_assign_s{sd}.csv"))

    geom, free, _starts, _goals = PS.setup_lifelong(
        os.environ["MAP"], n, pitch, int(sd), verbose=False)
    st = FileOrderStream(csv_path, geom, free, os.environ["MAP"], horizon)

    print(f"\n── 인덱스 검사 ──")
    bad = st.verify()
    if bad:
        print(f"   ★ `cells_by_cat[cat][i]` 가 원본 i 번째와 다른 데가 "
              f"{len(bad)}곳 —")
        for cat, i, mine, theirs in bad[:8]:
            print(f"     {cat}[{i}]: 원본 {mine} vs station_cells {theirs}")
        print(f"   우리는 **원본 인덱스**에서 변환하므로 영향은 없다.")
        print(f"   그러나 `cells_by_cat` 을 번호로 읽는 코드가 있다면 틀린다.")
    else:
        print(f"   점 항목 전부가 인덱스별로 같은 칸을 낸다 — 안 밀린다")

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
