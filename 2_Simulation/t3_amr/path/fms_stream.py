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
import json
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

    def _setup_stations(self, geom, free, map_dir):
        """이름 -> 칸 해석에 필요한 것들. `JsonOrderStream` 도 같은 것을 쓴다.

        ☹ `pibt_scene` 은 **여기서 늦게** 임포트한다. 그것이 `3_FMS/sim_engine`
          을 `sys.path` 에 넣는 쪽이라 모듈 최상단에서 부르면 순서가 꼬인다.
        """
        import pibt_scene as PS
        self._pts = PS.load_stations(map_dir)
        self._geom, self._free, self._PS = geom, free, PS
        self._map = map_dir
        self._cache = {}

    def _init_common(self, path, sha, geom, free, map_dir, horizon, order_end):
        """두 스트림이 공유하는 상태 조립.

        커널이 보는 넷(`arrivals` · `n_task` · `windows` · `order_end`)이 여기서 선다.
        교대 창은 파일이 정하므로 한 칸으로 둔다 — 커널은 `info` 에만 쓴다.
        """
        self.path = path
        self.sha256 = sha
        self.horizon = int(horizon)
        self.order_end = _opt_tick(order_end)
        self.n_task = 0
        self.windows = [("out", 0, self.horizon)]
        self._setup_stations(geom, free, map_dir)
        self._by_tick = collections.defaultdict(list)
        self.skipped_late = 0        # 창 밖이라 버린 것
        self.skipped_bad = []        # 칸을 못 찾은 것
        self.total = 0

    def __init__(self, csv_path, geom, free, map_dir, horizon,
                 order_end=None, verbose=True):
        self._init_common(csv_path, sha256(csv_path), geom, free, map_dir,
                          horizon, order_end)
        self._init_scale(geom)
        self._load_csv(csv_path)
        self.loaded = sum(len(v) for v in self._by_tick.values())
        if verbose:
            self._report_csv()

    def _init_scale(self, geom):
        """파일 틱 -> 우리 틱 배율. pitch 1.0 이면 정확히 1.0 이다.

        ★ 도착 분포는 **파일 전체**로 센다 — horizon 과 무관하게 (2026-09-17).
          `loaded`(horizon 안)로 재면 horizon 이 30분보다 짧을 때 전부가
          「첫 30분」이라 100 % 가 나오고, 단언 ③ 이 거짓 경보를 낸다. 실제로
          `run_lifelong(horizon=1260)` 에서 그렇게 터졌다. 이 값은 「어떤
          파일인가」를 묻는 것이지 「우리가 얼마나 쓰나」가 아니다.
          첫 30분은 **파일 틱**으로 잰다 (파일의 성질이므로 파일 dt 로).
        """
        self._early_win = round(1800.0 / DT)
        self._early_all = 0
        self.dt_file = DT
        self.dt_ours = our_dt(geom)
        self.tick_scale = self.dt_file / self.dt_ours
        self.rescaled = abs(self.tick_scale - 1.0) > 1e-12

    def _load_csv(self, csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self.total += 1
                self._row(row)

    def _row(self, row):
        t_file = int(row["created_tick"])
        if t_file < self._early_win:
            self._early_all += 1
        t = t_file if not self.rescaled else int(round(t_file * self.tick_scale))
        if t >= self.horizon:
            self.skipped_late += 1
            return
        frm = self._resolve(row["frm_name"])
        to = self._resolve(row["to_name"])
        if frm is None or to is None:
            self.skipped_bad.append((row["frm_name"], row["to_name"]))
            return
        self._by_tick[t].append({"kind": "out", "frm": frm, "to": to, "born": t})

    def _report_csv(self):
        print(f"[fms_stream] {os.path.basename(self.path)} · "
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


class JsonOrderStream(FileOrderStream):
    """백엔드 `scenario.orders` → lifelong 주문 스트림. **배정 전 형태를 받는다.**

    `FileOrderStream` 이 읽는 `packing_assign_*.csv` 는 FMS 의 **출력**이라
    `frm_name`·`to_name` 이 이미 정해져 있다. 백엔드가 보내는 것은 그 앞 단계다.

        {"order_id": 1, "ordered_at_s": 23659,
         "lines": [{"product_id": 3, "qty": 2, "rack_id": "A3"}]}

    「무엇을 얼마나」만 있고 「어디서 어디로」가 없다. 그 둘을 만드는 규칙은
    **FMS 에 이미 있고**, 여기서는 그것을 그대로 옮긴다 (추측하지 않는다).

        rack_id -> 버퍼   warehouse/map/rack_buffers.json 의 `racks`
                          3_FMS/sim_engine/order_stream.py:256-259 와 같은 표
        토트 묶기         같은 버퍼는 qty 를 합쳐 ceil(합 / tote_units)
                          같은 파일 `_parse_order` 와 같은 식
        포장대            **주문마다 균등 난수 1 draw** — 그 주문의 토트는 전부
                          같은 포장대로 간다 (order_stream.py:189, 주석에
                          "포장대는 시뮬(WMS 역할)이 배정")
        도착 틱           round(ordered_at_s / our_dt(geom))
                          CSV 의 `created_tick` 과 달리 초로 오므로 환산이 한 번이다

    ☹ 포장대 난수는 **FMS 의 뽑기와 같은 수열이 아니다.** 정책은 같지만 어느
      주문이 어느 포장대로 갈지는 다르다. 비트 동일이 필요하면 FMS 의 배정표
      CSV(`FileOrderStream`)나 궤적(`PIBT_TRAJ`)을 써야 한다. 이 스트림은
      「백엔드 주문으로 실제로 돌려 본다」는 목적이지 정합성 대조용이 아니다.
    """

    # ── 만들기 ───────────────────────────────────────────────────────────
    #   생성자는 **조립만** 한다. 파일을 읽는 것은 `from_file` 이다 —
    #   그래야 주문 목록만 있으면 디스크 없이 단위 테스트가 된다.

    @classmethod
    def from_file(cls, json_path, geom, free, map_dir, horizon, **kw):
        """`scenario.json`(또는 주문 파일) → 스트림. 부수효과는 여기에만 있다."""
        return cls(_scenario_orders(json_path), geom, free, map_dir, horizon,
                   racks=_rack_map(map_dir), path=json_path,
                   sha=sha256(json_path), **kw)

    def __init__(self, orders, geom, free, map_dir, horizon, racks, seed=0,
                 tote_units=10, order_end=None, window_start_s=None,
                 path="<메모리>", sha="", verbose=True):
        self._init_common(path, sha, geom, free, map_dir, horizon, order_end)
        self._init_scale(geom)
        self.total = len(orders)
        self._spawn(orders, racks, int(seed), int(tote_units), window_start_s)
        self.loaded = sum(len(v) for v in self._by_tick.values())
        if verbose:
            self._report_json(seed, tote_units)

    def _init_scale(self, geom):
        """CSV 와 달리 **초**로 오므로 환산이 한 번이다. 파일 틱 배율이 없다."""
        self.dt_file = self.dt_ours = our_dt(geom)
        self.tick_scale, self.rescaled = 1.0, False

    # ── 주문 -> 토트 태스크 ──────────────────────────────────────────────
    def _spawn(self, orders, racks, seed, tote_units, window_start_s):
        n_pack = len(self._pts.get("packing") or ())
        if not n_pack:
            raise RuntimeError("stations.json 에 packing 이 없다 — 포장대를 못 고른다")
        rng = _np().random.default_rng(seed)
        for od in orders:
            t = _arrival_tick(od, self.dt_ours, window_start_s, self.horizon)
            if t is None:
                self.skipped_late += 1
                continue
            group, bad = _group_by_buffer(od.get("lines") or (), racks)
            if bad:
                self.skipped_bad.extend(bad)
                continue
            if not group:
                continue
            # ★ 포장대는 **주문당 한 번** 뽑는다. 토트마다 뽑으면 한 주문이
            #   여러 포장대로 흩어져 FMS 와 다른 문제가 된다.
            to = self._resolve("packing[%d]" % int(rng.integers(n_pack)))
            for b, n_tote in _totes(group, tote_units):
                self._add(b, to, n_tote, t)

    def _add(self, buf, to, n_tote, t):
        frm = self._resolve("aisle_buf[%d]" % buf)
        if frm is None or to is None:
            self.skipped_bad.append("aisle_buf[%d]" % buf)
            return
        for _ in range(n_tote):
            self._by_tick[t].append({"kind": "out", "frm": frm, "to": to, "born": t})

    def _report_json(self, seed, tote_units):
        print(f"[fms_stream] {os.path.basename(self.path)} · 주문 {self.total:,}건 -> "
              f"**토트 {self.loaded:,}개** 적재 (horizon {self.horizon:,}틱 · "
              f"dt {self.dt_ours:.6f}s · tote_units {tote_units})", flush=True)
        if self.skipped_late:
            print(f"[fms_stream]   창 밖이라 뺌 {self.skipped_late:,}건", flush=True)
        if self.skipped_bad:
            print(f"[fms_stream]   ★ 랙을 못 찾음 {len(self.skipped_bad)}건 — "
                  f"예: {self.skipped_bad[:3]}", flush=True)
        print("[fms_stream]   ☹ 포장대는 우리 난수로 배정했다 (seed %d) — "
              "FMS 와 **같은 정책, 다른 뽑기**다" % int(seed), flush=True)


# ── 순수 함수 — 파일도 클래스 상태도 안 본다 (단위 테스트용) ──────────────
def _opt_tick(v):
    """선택적 틱 값 — 없으면 None, 있으면 음수 없는 정수. 호출부의 분기를 없앤다."""
    return None if v is None else max(0, int(v))


def _arrival_tick(order, dt, window_start_s, horizon):
    """주문 하나 → 도착 틱. 창 밖이면 None.

    `window_start_s` 는 host-orch 가 시각을 안 당겨 줬을 때만 준다 — 이미
    0 기준으로 정규화된 목록에 또 빼면 전부 음수가 된다.
    """
    t_s = float(order.get("ordered_at_s", 0.0))
    if window_start_s:
        t_s -= float(window_start_s)
    if t_s < 0:
        return None
    t = int(round(t_s / dt))
    return None if t >= horizon else t


def _group_by_buffer(lines, racks):
    """라인들 → ({버퍼: qty 합}, 못 찾은 rack_id 목록).

    못 찾은 것이 하나라도 있으면 **그 주문 전체를 버린다** — 일부만 실으면
    수요가 조용히 줄어 비교가 깨진다.
    """
    group, bad = {}, []
    for ln in lines:
        rid = ln.get("rack_id")
        if rid not in racks:
            bad.append(rid)
            return {}, bad
        group[racks[rid]] = group.get(racks[rid], 0) + int(ln.get("qty", 1))
    return group, bad


def _totes(group, tote_units):
    """{버퍼: qty} → [(버퍼, 토트 수)]. FMS `order_stream._parse_order` 와 같은 식."""
    return [(b, -(-q // tote_units) if tote_units else 1)
            for b, q in sorted(group.items())]


def _np():
    import numpy
    return numpy


def _rack_map(map_dir):
    """`rack_buffers.json` 의 `racks` — rack_id -> aisle_buf 인덱스.

    FMS `3_FMS/map/rack_buffers.json` 과 같은 파일이고, 그 규칙은 파일 안에
    적혀 있다: "rack -> zone -> facility(x,y) == stations.json aisle_buf[i]
    (정확 일치, 최근접 아님)".
    """
    p = os.path.join(map_dir, "rack_buffers.json")
    if not os.path.isfile(p):
        raise RuntimeError(
            "rack_buffers.json 이 없다: %s\n"
            "  백엔드 주문은 rack_id 로 오므로 이 표가 있어야 버퍼를 정한다.\n"
            "  원본: 3_FMS/map/rack_buffers.json" % p)
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    racks = d.get("racks") if isinstance(d, dict) else None
    if not isinstance(racks, dict) or not racks:
        raise RuntimeError("rack_buffers.json 에 `racks` 가 없다: %s" % p)
    return racks


def _scenario_orders(path):
    """`scenario.json` 또는 주문 파일 → outbound 리스트.

    받는 모양이 셋이다 — edge 가 떨어뜨린 `scenario.json`(그 안에 orders),
    생성기 산출물 `{meta, outbound}`, 그리고 리스트 그대로.
    """
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if isinstance(d, dict) and "scenario" in d:          # Start 페이로드 통째
        d = d["scenario"]
    if isinstance(d, dict) and "orders" in d:            # scenario.json
        d = d["orders"]
    if isinstance(d, dict):
        d = d.get("outbound")
    if not isinstance(d, list):
        raise RuntimeError("주문 목록을 못 찾았다 (scenario.orders.outbound): %s" % path)
    return d


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
