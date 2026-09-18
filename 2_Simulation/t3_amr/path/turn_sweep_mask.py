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

비용 (pitch 1.0 · 우리 맵 · 시드 103)
-------------------------------------
    금지되는 회전   60,192건 중 **1,800건 (3.0 %)** · 최대 침투 471 mm
                    (pitch 1.2 면 **0.3 %** — 이 대가는 pitch 에 매여 있다)

    ☹ **정적 그래프 추정이 한 자릿수 낮았다** (2026-09-18 정정)
        추정   도달 -0.28 % · 경로 +1 % 미만      <- 전 상태 평균이라 통행 분포를 못 본다
        실측   칸 이동 총수는 **같다**(101,771 -> 101,783). move 7,148건이 reverse 로.
               주행비용(move + 3 x reverse)  **+11.9 %**
               왕복 환산(주행이 왕복의 87.5 %) **+10.4 %**
               실행(같은 sim 시각 완료 액션)   **-3.3 ~ -5.7 %**
        셋은 **서로 다른 자다.** 가부는 여기서, 값은 주행에서 잰다.
"""
import hashlib
import math
import os

import numpy as np

TURN_SWEEP_ON = os.environ.get("PIBT_TURN_SWEEP", "0") not in ("0", "", "no", "off")
BAN_MM = float(os.environ.get("PIBT_TURN_SWEEP_MM", "0"))
SAMPLES = int(os.environ.get("PIBT_TURN_SWEEP_SAMPLES", "48"))
DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1)]
# (이 모듈은 마스크만 만든다. 회전 대기 게이트 상수는 `isaac_drive` 에 있다.)


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
    """회전 중 차체가 장애물을 몇 m 파고드나. 반환 (최대침투, 그때 각도 deg, 여유는 안 낸다).

    픽셀은 **점이 아니라 0.1 m 사각형**이다. 중심만 보면 최대 50 mm 를 덜 센다 —
    실제로 a6 의 회전이 「2 mm」로 나와 애매하다고 읽힐 뻔했고, SAT 로 바꾸니
    **58 mm** 였다. 축은 넷이면 된다 (차체 전방·좌측 + world x·y).
    """
    from isaac_drive import YAW, wrap
    cx, cy, _ = geom.state_pose((r, c, h0))
    y0, y1 = YAW[geom.phys_heading(h0)], YAW[geom.phys_heading(h1)]
    dth = wrap(y1 - y0)

    best_pen, best_ang = 0.0, 0.0
    for s in range(samples + 1):
        yaw = y0 + dth * (s / samples)
        pen = pose_penetration(geom, cx, cy, yaw, obst=obst)
        if pen > best_pen:
            best_pen, best_ang = pen, math.degrees(dth * (s / samples))
    # 여유(안 닿을 때의 최소 거리)는 이제 안 낸다 — `pose_penetration` 이
    # 겹침만 돌려준다. 쓰는 곳이 「닿나/얼마나」뿐이라 뺐다.
    return best_pen, best_ang, (float("inf") if best_pen <= 0.0 else 0.0)


# ===========================================================================
# 정적 접촉 감시 (L, 2026-09-18) — 합불 기준이 **랙을 안 봤다**
# ===========================================================================
#
#   `FleetController` 는 접촉을 이렇게 센다.
#
#       gap = self.g.body_gap(poses[a], poses[b])   # 로봇 a 와 로봇 b 사이
#       if gap <= 0.0: self.stats.contact_events += 1
#
#   **로봇끼리만 본다.** 그래서 차체가 랙에 58 mm 박혀 있는 동안에도
#   `contact_events=0 · worst_gap=0.297 m` 로 「깨끗함」이었고, 판의 합불이
#   그 값으로 갈렸다. 원인(랙 침투)은 어느 지표에도 안 잡혔다.
#
#   그 구멍을 메운다. 같은 0.1 m 마스크와 같은 SAT 를 쓴다 — 정의가 두 벌이
#   되면 「도구는 닿는다는데 주행은 아니라고 한다」가 난다.
#
#   ☹ 싸야 한다. 12대 x 60 Hz 다. 그래서 **칸 단위로 먼저 거른다** —
#     장애물 픽셀이 하나라도 있는 1 m 칸을 미리 모아 두고, 차체가 덮는 칸이
#     거기 안 닿으면 SAT 를 아예 안 돌린다. 통로 한가운데서는 공짜다.

_OBST = None            # (0.1 m bool 배열, 장애물이 있는 1 m 칸 집합, 출처)


def prepare_contact(geom, map_dir, verbose=True):
    """정적 접촉 감시 준비. `setup_lifelong` 이 판마다 한 번 부른다."""
    global _OBST
    obst, src = load_obstacle_mask(map_dir)
    k = int(round(geom.pitch / 0.1))
    R, C = obst.shape[0] // k, obst.shape[1] // k
    hit = obst[:R * k, :C * k].reshape(R, k, C, k).any(axis=(1, 3))
    cells = frozenset((int(r), int(c)) for r, c in zip(*np.nonzero(hit)))
    _OBST = (obst, cells, src)
    # ★ 이것도 **항상** 찍는다. 이 줄이 없으면 합불(`clean`)이 랙을 보고 있는지
    #   모르는 채로 「완주했다」를 쓰게 된다 — 그게 L 을 만든 이유다.
    print(f"[static] ★ 랙 접촉 감시 켬 — {src} · 장애물 칸 {len(cells):,}개",
          flush=True)
    return _OBST


def obstacle_cells():
    """장애물이 있는 1 m 칸 집합. 준비 전이면 None."""
    return None if _OBST is None else _OBST[1]


def pose_penetration(geom, x, y, yaw, obst=None):
    """이 **자세 하나**에서 차체가 정적 장애물을 몇 m 파고드나 (0 이면 안 닿는다).

    ★ `penetrate()`(회전 스윕)도 **이 함수를 샘플마다 부른다.** 식이 두 벌이
      되면 「도구는 닿는다는데 주행은 아니라고 한다」가 나기 때문이다.
      회전 직사각형 대 축정렬 정사각형의 분리축 정리 — 축 넷이면 된다.
    """
    if obst is None:
        if _OBST is None:
            return 0.0
        obst = _OBST[0]
    rad = math.hypot(geom.rear_len, geom.width / 2.0) + 0.02
    i0 = max(0, int((y - rad) / 0.1)); i1 = min(obst.shape[0], int((y + rad) / 0.1) + 1)
    j0 = max(0, int((x - rad) / 0.1)); j1 = min(obst.shape[1], int((x + rad) / 0.1) + 1)
    if i1 <= i0 or j1 <= j0:
        return 0.0
    ii, jj = np.nonzero(obst[i0:i1, j0:j1])
    if len(ii) == 0:
        return 0.0
    px = (jj + j0 + 0.5) * 0.1 - x
    py = (ii + i0 + 0.5) * 0.1 - y
    hv = geom.width / 2.0
    hu = (geom.rear_len + geom.front_len) / 2.0
    cu = (geom.front_len - geom.rear_len) / 2.0
    q = 0.05
    f, l = math.cos(yaw), math.sin(yaw)
    dx, dy = px - cu * f, py - cu * l
    o1 = (hu + q * (abs(f) + abs(l))) - np.abs(dx * f + dy * l)
    o2 = (hv + q * (abs(l) + abs(f))) - np.abs(-dx * l + dy * f)
    o3 = (q + hu * abs(f) + hv * abs(l)) - np.abs(dx)
    o4 = (q + hu * abs(l) + hv * abs(f)) - np.abs(dy)
    return max(float(np.minimum(np.minimum(o1, o2), np.minimum(o3, o4)).max()), 0.0)


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
    # ★ `verbose` 와 무관하게 **항상** 찍는다 (트러블슈팅 (더), 2026-09-18).
    #   `live_pibt` 가 `setup_lifelong(..., verbose=False)` 로 부르는 바람에
    #   이 줄이 통째로 묻혔다 — 마스크가 걸렸는지를 **액션 수로 역추적**해서
    #   확인해야 했다. 기본과 다른 상태는 보여야 한다.
    print(f"[turn_sweep] ★ 계획기에 걸었다 — 회전 {int((~m).sum()):,}건 금지 "
          f"(PIBT_TURN_SWEEP=1 · 문턱 {BAN_MM:.0f} mm)", flush=True)
    return m
