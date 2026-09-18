# -*- coding: utf-8 -*-
"""회전 스윕이 **정적 장애물과 겹치나** — `pibt.geometry.configure(turn_mask=…)` 용 (S15P21A106-240).

왜 이것이 필요한가
------------------
`turn_ok` 는 **스윙 대각 한 칸**만 본다. 그런데 제자리 90도 회전의 실제 스윕은
6칸이고 그중 예약 밖이 3칸이다 — 검사는 그 셋 중 하나만 한다.

    turn(46,68,3)->(46,68,0)
        스윕 6칸  [(45,68) (45,69) (46,67) (46,68) (46,69) (47,68)]
        예약 3칸  [(45,68) (46,68) (46,69)]
        turn_ok 가 보는 칸  [(45,69)]        <- 비어 있다. 통과
        막힌 칸             **(47,68)**      <- 검사 대상이 아니다

그래서 계획이 **차체가 랙을 58 mm 파고드는 회전**을 냈다. Isaac 의 랙 콜라이더가
밀어내면서 회전이 363 mm 밀렸고(시작 48.4 -> 끝 363.4), 다음 액션이 진입 횡오차
362 mm 를 물려받았다. 한 액션이 지울 수 있는 상한은 **90 mm**(감쇠 55.8 %)라
구조적으로 못 끝내고, 제어기는 평형(`head = K_CROSS/K_HEAD · cross`)에 앉아
`w = -0.000` 이 된다. **제어로는 못 막는다.**

왜 FMS 코드를 안 고치나
-----------------------
**고칠 필요가 없다.** `pibt/geometry.py` 에 자리가 이미 있다.

    _TURN_MASK = None    # bool[H, W, 4, 4] — [r,c,h,h2] = 회전 스윕이 장애물과 안 겹침
    def configure(turn_mask=None, ...)
    def turn_ok(...):  ...  return _TURN_MASK is None or bool(_TURN_MASK[r, c, h, h2])

`hgraph_for` 의 캐시 키에도 마스크 해시가 들어 있어 테이블이 조용히 낡지 않는다.
**아무도 마스크를 안 넣고 있었을 뿐이다.** 이 모듈이 그 마스크를 만든다.

재는 법
-------
1 m 칸 판정은 쓰면 안 된다 — `build_free(mode="cross")` 가 칸의 **중앙 행·열만**
보므로 「칸은 비었는데 귀퉁이는 막힌」 경우를 놓치고 반대로 부풀리기도 한다.
원본 0.1 m 마스크의 픽셀을 **0.1 m 정사각형**으로 두고, 회전 48 샘플마다 차체
직사각형과 **분리축 정리(SAT)** 로 맞댄다.

비용 (2026-09-17 실측, pitch 1.0 · 우리 맵)
-------------------------------------------
    금지되는 회전       60,192건 중 **1,800건 (3.0 %)** · 최대 침투 471 mm
    도달 가능 상태      7,198 -> 7,178   **-20개 (0.28 %)**
    경로 길이           평균 +1.4~3.1틱 · p95 +5~10틱 ~ **왕복의 1 % 미만**

☹ 정적 그래프 기준이다. PIBT 는 함대 알고리즘이라 혼잡이 더해져 **이보다 나쁘다.**
"""
import hashlib
import math
import os

import numpy as np

TURN_SWEEP_ON = os.environ.get("PIBT_TURN_SWEEP", "0") not in ("0", "", "no", "off")
BAN_MM = float(os.environ.get("PIBT_TURN_SWEEP_MM", "0"))
SAMPLES = int(os.environ.get("PIBT_TURN_SWEEP_SAMPLES", "48"))
DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1)]


def load_obstacle_mask(map_dir):
    """원본 0.1 m 장애물 마스크 (True = 막힘). `pibt_scene.build_free` 와 같은 출처·같은 규칙."""
    import pibt_scene as PS
    src = PS._pick(map_dir, "occupancy_grid.npy", "obstacle_mask.npy",
                   "obstacle_mask_wallA.npy")
    g = np.load(src)
    if os.path.basename(src) == "occupancy_grid.npy":
        cfg = getattr(PS, "_CFG", None)
        vals = getattr(cfg, "OBSTACLE_VALUES", (1, 2, 5, 6)) if cfg else (1, 2, 5, 6)
        m = np.isin(g, vals)
    else:
        m = g.astype(bool)
    cfg = getattr(PS, "_CFG", None)
    if cfg is not None and getattr(cfg, "AISLE_BLOCK", False):
        m = cfg.apply_aisle_block(m.copy())
    return m, os.path.basename(src)


def penetrate(obst, geom, r, c, h0, h1, samples=SAMPLES):
    """회전 중 차체가 장애물을 몇 m 파고드나. 반환 (최대침투, 그때 각도 deg, 최소여유).

    픽셀은 **점이 아니라 0.1 m 사각형**이다. 중심만 보면 최대 50 mm 를 덜 센다 —
    실제로 a6 의 회전이 「2 mm」로 나와 애매하다고 읽힐 뻔했고, SAT 로 바꾸니
    **58 mm** 였다. 축은 넷이면 된다 (차체 전방·좌측 + world x·y).
    """
    from isaac_drive import YAW, wrap
    cx, cy, _ = geom.state_pose((r, c, h0))
    y0, y1 = YAW[geom.phys_heading(h0)], YAW[geom.phys_heading(h1)]
    dth = wrap(y1 - y0)

    rad = math.hypot(geom.rear_len, geom.width / 2.0) + 0.15
    i0 = max(0, int((cy - rad) / 0.1)); i1 = min(obst.shape[0], int((cy + rad) / 0.1) + 1)
    j0 = max(0, int((cx - rad) / 0.1)); j1 = min(obst.shape[1], int((cx + rad) / 0.1) + 1)
    ii, jj = np.nonzero(obst[i0:i1, j0:j1])
    if len(ii) == 0:
        return 0.0, 0.0, float("inf")
    px = (jj + j0 + 0.5) * 0.1 - cx
    py = (ii + i0 + 0.5) * 0.1 - cy

    hv = geom.width / 2.0
    hu = (geom.rear_len + geom.front_len) / 2.0
    cu = (geom.front_len - geom.rear_len) / 2.0
    q = 0.05
    best_pen, best_ang, best_gap = 0.0, 0.0, float("inf")
    for s in range(samples + 1):
        yaw = y0 + dth * (s / samples)
        f, l = math.cos(yaw), math.sin(yaw)
        dx, dy = px - cu * f, py - cu * l
        o1 = (hu + q * (abs(f) + abs(l))) - np.abs(dx * f + dy * l)
        o2 = (hv + q * (abs(l) + abs(f))) - np.abs(-dx * l + dy * f)
        o3 = (q + hu * abs(f) + hv * abs(l)) - np.abs(dx)
        o4 = (q + hu * abs(l) + hv * abs(f)) - np.abs(dy)
        pen = float(np.minimum(np.minimum(o1, o2), np.minimum(o3, o4)).max())
        if pen > best_pen:
            best_pen, best_ang = pen, math.degrees(dth * (s / samples))
        if pen <= 0.0:
            best_gap = min(best_gap, -pen)
    return max(best_pen, 0.0), best_ang, best_gap


def _cache_path(free, geom, ban_mm):
    key = hashlib.sha1(
        free.tobytes()
        + repr((round(geom.pitch, 6), geom.rear_len, geom.front_len,
                geom.width, ban_mm, SAMPLES)).encode()
    ).hexdigest()[:16]
    base = os.environ.get("PIBT_CACHE") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache")
    return os.path.join(base, f"turnmask_{key}.npy")


def build(free, geom, map_dir, ban_mm=None, verbose=True):
    """bool[H, W, 4, 4] 마스크. True = 그 회전은 장애물과 안 겹친다.

    인접 헤딩 쌍만 채운다 — `turn_ok` 가 h±1 로만 부른다. 나머지는 True 로 둔다
    (읽히지 않는다). 디스크 캐시는 free 내용·기하·문턱으로 키를 만든다.
    """
    ban_mm = BAN_MM if ban_mm is None else ban_mm
    path = _cache_path(free, geom, ban_mm)
    if os.path.isfile(path):
        m = np.load(path)
        if verbose:
            print(f"[turn_sweep] 캐시 {os.path.basename(path)}  "
                  f"금지 {int((~m).sum()):,}건")
        return m

    obst, src = load_obstacle_mask(map_dir)
    H, W = free.shape
    m = np.ones((H, W, 4, 4), dtype=bool)
    banned = 0
    worst = 0.0
    for r in range(H):
        for c in range(W):
            if not free[r, c]:
                continue
            for h in range(4):
                for h2 in ((h + 1) % 4, (h - 1) % 4):
                    pen, _a, _g = penetrate(obst, geom, r, c, h, h2)
                    if pen * 1000.0 > ban_mm:
                        m[r, c, h, h2] = False
                        banned += 1
                        worst = max(worst, pen)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.save(path, m)
    if verbose:
        print(f"[turn_sweep] {src} 로 계산  금지 {banned:,}건 · 최대 침투 "
              f"{worst * 1000:.0f} mm · 문턱 {ban_mm:.0f} mm")
        print(f"[turn_sweep] 캐시 저장 {path}")
    return m


def apply(free, geom, map_dir, verbose=True):
    """마스크를 만들어 계획기에 건다. `PIBT_TURN_SWEEP` 이 꺼져 있으면 아무것도 안 한다.

    ★ `configure()` 는 `front_swing`·`front_diag` 도 같이 덮어쓴다. 지금 켜져
      있는 값을 그대로 다시 넣어야 `_check_front_swing` 이 안 죽는다.
      `robot_dims` 는 **안 준다** — 주면 pitch 게이팅이 다시 돌아 값이 바뀐다.
    """
    if not TURN_SWEEP_ON:
        return None
    try:
        import pibt.geometry as geo
    except ImportError:
        print("[turn_sweep] ☹ 계획기 기하를 못 불러온다 — 마스크를 못 건다")
        return None
    if not hasattr(geo, "configure"):
        print("[turn_sweep] ☹ 이 계획기에는 configure 가 없다 — 상류가 낡았다")
        return None
    m = build(free, geom, map_dir, verbose=verbose)
    geo.configure(turn_mask=m,
                  front_swing=bool(geo.front_swing_on()),
                  front_diag=bool(geo.front_diag_on()))
    if verbose:
        print(f"[turn_sweep] ★ 계획기에 걸었다 — 회전 {int((~m).sum()):,}건 금지")
    return m
