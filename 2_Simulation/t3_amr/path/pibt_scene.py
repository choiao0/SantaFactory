# -*- coding: utf-8 -*-
"""v5.9 팀 창고 맵을 pibt_core_v2 / isaac_drive 가 쓰는 형태로 바꾼다.

    python pibt_scene.py --n 12 --pitch 1.2 --out ../../v2/traj_pibt_h/fleet_12

로컬에서 `starts.json` 을 먼저 뽑아 씬을 빌드하고, 서버의 `live_pibt.py` 가
**같은 시드로 같은 격자·같은 시작/목표**를 재현해 주행한다. 계획은 결정적이라
양쪽이 반드시 일치한다.

[의존]
numpy · pibt_core_v2 · isaac_drive 를 쓰고, 통로차단 규칙 때문에 config 도 읽는다
(82행. 예전에 "config/grid 를 import 하지 않는다"고 적었으나 사실이 아니다 —
2026-09-08 정정). grid 는 여전히 안 쓰는
이유는 서버에 올릴 파일 수를 줄이기 위해서다 (4개면 된다).

[격자]
`obstacle_mask.npy` 는 0.1 m 이고 **이미 AMR 반경 0.8 m 로 팽창**돼 있다.
여기에 "블록 전체가 비어야 통행가능"을 적용하면 팽창이 이중으로 걸려 통로가
사라진다 (pibt_to_traj.py 에서 실측: 2.4 m 격자에서 전원 미도달).
그래서 중앙 행·열만 보는 `cross` 풀링을 기본으로 쓴다.

[피치가 아무 값이나 되지 않는다]
isaac_drive 의 2칸 점유 + 스윙 3칸 모델은 아래 구간에서만 성립한다.

    하한  2 * hypot(front_len, width/2) = 1.016 m   짧은 쪽이 자기 칸에 머묾
    상한  2 * rear_len                  = 2.060 m   긴 쪽이 이웃 칸에 닿음

**우리 WPPL 격자 2.4 m 는 상한 밖이고, FMS 의 1.0 m 는 하한 밖이다.**
기본값 1.2 m 는 그 사이다. `RobotGeom.audit()` 가 확인해 준다.
"""
import argparse
import json
import math
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# isaac_drive.py 는 `from pibt_core import ...` 로 되어 있다 (팀 저장소의 모듈명).
# 우리 쪽 파일 이름은 pibt_core_v2.py 이므로 별칭을 먼저 걸어 준다.
# 파일을 복사하거나 이름을 바꾸지 않는 이유: 팀의 pibt_core.py 와 헷갈리지 않게,
# 그리고 v2 를 갱신할 때 한 파일만 바꾸면 되게 하려는 것이다.
import pibt_core_v2 as _pc                             # noqa: E402
sys.modules.setdefault("pibt_core", _pc)

# REVERSE_FACTOR 는 **덮어쓰지 않는다** (2026-09-07, FMS develop 정렬).
#
#   develop 판 pibt_core.py 는 `pos - DIRS[h]`(물리 후진)에 3.0 을 붙인다.
#   우리 에셋은 heading_offset=0 이고 그것이 이 규칙과 짝이므로 기본값이 맞다.
#
#   [경위] 한때 REVERSE_FACTOR 를 1/3 로 뒤집어 두었다. 미머지 판(pos + DIRS[h]
#   에 배율을 붙인 것)을 받아 쓰면서 전진에 3배 벌점이 붙었기 때문이다
#   (전진 70 / 후진 932). FMS 본판으로 정렬하면서 그 우회를 걷어냈다.
#
#   [두 판 실측 — 12대, pitch 1.2, max_steps 400]
#       seed   미머지판 + 1/3            develop + 3.0
#         4    OK  전진 90%  turn 108    STALL
#         5    OK  전진 93%  turn 110    OK  전진 92%  turn 236
#         9    OK  전진 93%  turn  90    STALL
#        11    STALL                     OK  전진 91%  turn 214
#        15    OK  전진 94%  turn  86    OK  전진 91%  turn 218
#
#   둘 다 전진 우세지만 동치가 아니다. develop 쪽은 회전이 2배 이상이다
#   (배율이 이동에 붙느냐 후진에 붙느냐에 따라 turn_cost 와의 비율이 3배 달라진다).
#   **회전이 많아지는 것은 9/4 선회 여유 결함과 겹치므로 주시해야 한다** —
#   정점의 12.6%가 소인반경 기준 회전 불가다.

# --- FMS 통로차단 ---
# 랙 사이 통로는 피커 전용이라 로봇이 못 간다. lattice/grid 는 이미 막는데
# 여기만 원본 마스크를 그대로 읽고 있었다 — 그러면 pibt_h 만 그 통로를 쓴다.
# 규칙은 config 한 곳에만 둔다 (FMS map_loader 와 1:1).
_CFG = None
for _d in (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "amr", "make_path"),
           os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "amr", "make_path"),
           os.path.dirname(os.path.abspath(__file__))):
    if os.path.isfile(os.path.join(_d, "config.py")):
        if _d not in sys.path:
            sys.path.append(_d)
        import config as _CFG                                  # noqa: E402
        break

# ★ 못 찾으면 **조용히 다른 격자가 만들어진다** — 아래 `build_free` 가
#   `apply_aisle_block` 을 건너뛰어 랙 사이 통로가 열린다. 계획이 달라지는데
#   아무 표시가 없다.
#
#   실제로 당했다 (2026-09-15). FMS 가 우리 도구를 재현하려고 `path/` ·
#   `warehouse/map` · `tools/` 만 꺼내 가고 이 파일을 빠뜨렸다. 통로가 열린
#   격자(9425칸 vs 8919칸)에서 계획이 돌아 시드별 틱 수가 전부 달랐고, 그것을
#   플랫폼 차이(Windows · Python 3.14 · numpy 2.5)로 의심하며 하루를 썼다.
#   파일을 넣자 우리 표가 **틱 수까지** 재현됐다.
#
#   그래서 조용히 넘어가지 않는다. stderr 로 낸다 — stdout 을 비교하는
#   도구들(지문·측정표)의 출력은 건드리지 않기 위해서다.
if _CFG is None:
    print("★ pibt_scene: amr/make_path/config.py 를 못 찾았습니다.\n"
          "  랙 사이 통로 차단(AISLE_BLOCK)이 꺼진 채로 격자가 만들어집니다 —\n"
          "  통로가 열려 **계획이 조용히 달라집니다** (실측 8919 -> 9425칸).\n"
          "  저장소 일부만 복사해 쓰는 경우 이 파일을 반드시 같이 가져오세요.",
          file=sys.stderr)

from isaac_drive import RobotGeom                      # noqa: E402
from pibt_core_v2 import valid_state, dist_map_h       # noqa: E402

# --- iw.hub 실측 (2026-09-03, iw_hub.usd 원본에서 직접) ---------------------
#   콜리전 차체 x ∈ [-1.030, +0.390], y ∈ ±0.325   전진 = +X
#   구동축은 chassis 원점(x=0). 캐스터가 뒤(x=-0.65)라 **구동축이 앞**이다.
#   base_link 원점 = 구동축 중점이므로 axle_in_prim = (0, 0).
GEOM_KW = dict(
    # --- 2026-09-13: 적재 선반(1,500 x 800 x 1,650)을 얹은 치수 (S15P21A106-196) ---
    #   인포그래픽 외형 1,500 - 차체 1,420 = 80 mm 를 **전부 뒤로** 붙였다.
    #   pitch 하한 = 2 * hypot(front_len, width/2) 라 **앞면과 폭만** 하한을 정한다.
    #       앞뒤 40 씩 :  하한 1.1746  ->  pitch 1.2 여유 +25.4 mm  (살얼음)
    #       뒤로 80    :  하한 1.1173  ->  pitch 1.2 여유 +82.7 mm  (채택)
    #   pitch 1.0 을 깨뜨렸던 위반량이 -7.7 mm 였으므로 +25.4 mm 는 같은 등급이다.
    #   ★ front_len 은 절대 건드리지 말 것 — 하한이 여기서 나온다.
    rear_len=1.110,          # 구동축 -> 선반 베이스 뒷면 (차체 1.030 + 80 mm)
    front_len=0.390,         # 구동축 -> 차체 앞면 ★ 불변
    width=0.800,             # 선반 폭 (차체 0.650)
    v_max=0.9,               # config.SPEED_PLAN
    w_max=1.8,               # amr_driver_v2.OMEGA_MAX
    a_lin=0.8,               # config.ACCEL_MAX
    a_ang=3.0,
    axle_in_prim=(0.0, 0.0),
    # ★ 0 = 구동축이 앞, 차체가 뒤. 우리 에셋이 이쪽이다.
    #   isaac_drive 기본값은 2(구동축이 뒤)이므로 반드시 명시한다.
    #   두 조합은 **같은 칸 집합**을 내므로 점유 검사로는 구별되지 않는다.
    #   근거는 에셋 실측이다: 캐스터가 x=-0.65, 1인칭 카메라가 x=+0.350.
    heading_offset=0,
)
WHEEL_RADIUS = 0.08          # iw_hub.usd 조인트 저작값
WHEEL_BASE = 0.5796          # localPos0 = ±0.28963
# ★ 2026-09-16 검증 (-224). 두 값을 USD 원본과 주행 기록 양쪽에서 다시 쟀다
#   (`tools/usd_wheels.py` · `tools/wheel_calib.py`).
#
#       R  저작 0.08     /iw_hub/left_wheel/Cylinder 반지름 0.5 x 스케일 0.16
#          역산 0.0800   12대 · 흩어짐 1e-5                      ★ 맞다
#
#       L  저작 0.57926  localPos0 ±0.28963 (스케일은 메시에만 걸려 조인트
#                        좌표와 무관하다)                        ★ 맞다
#          실효 0.6759   12대 · 흩어짐 0.00279 (0.4%)            ★ 1.166 배
#
#   저작값은 맞는데 **실효 트랙폭이 16.6% 넓다.** 제자리 회전에서 타이어가
#   옆으로 긁히는 저항 때문이고, 12대가 0.4% 안에 모이므로 로봇별 결함이
#   아니라 상수 성질이다.
#
#   [무엇이 달라지나] 드라이버가 이 `L` 로 역기구학을 풀어 바퀴 속도를 낸다.
#   그래서 `w` 를 명령해도 실제로는 **0.857 배만** 돈다 (0.5796/0.6759).
#   회전이 모델보다 16.6% 오래 걸린다는 뜻이다.
#
#   ★ **일부러 안 고쳤다.** 여기를 0.676 으로 바꾸면 회전이 빨라지는 대신
#     꼬리 스윕과 ADG 타이밍이 같이 움직인다. 주행 전체가 바뀌는 변경이라
#     측정을 붙여서 따로 해야 한다. 지금은 기록만 남긴다.
#
#   [옆 효과] `tools/swivel_sweep.py` 의 접지비 중앙 0.91 은 미끄러짐이
#   아니라 이 차이였다 — 0.5796/0.6759 = 0.857 로 같은 자리다.

# 씬 빌더(build_amr_scene_v2.py)와 같은 충전존. 여기서 출발한다.
# [patch_charge_start] 충전존 시작 슬롯을 좌측 하단부터 일정 간격으로 생성
#   예전 값은 하드코딩 12칸이었다:
#       [(105.5, y) for y in (50,53,56,59,62,65)] + [(107.8, y) for ...]
#   원래 규칙적(x 2.3 · y 3.0)인데 _cell_of 가 1.2 m 격자로 스냅하면서
#   2셀/3셀로 번갈아 떨어져 불규칙해졌다 (2026-09-09 실측: 49.8·53.4·55.8·
#   59.4·61.8·65.4). ★ 간격이 pitch 의 배수가 아니면 규칙적일 수 없다.
#   그래서 슬롯을 **셀 중심 위에서 직접** 만든다.
#
#   또 `CHARGE_ZONE[:n]` 이라 n>12 면 starts 가 12개만 담기고 목표 루프의
#   starts[a] 에서 KeyError 로 죽었다. 이제 존이 허용하는 만큼 나온다.
CHARGE_RECT = (102.6, 48.0, 108.6, 67.0)   # warehouse/map/charge_zone.json "east"
# ★★ 격자·홈·헤딩·마스크를 FMS 것으로 (-240). 자세한 근거는 `_fms_setup` 머리말.
FMS_GRID = os.environ.get("PIBT_FMS_GRID", "0") not in ("0", "", "no", "off")
CHARGE_LAT = float(os.environ.get("PIBT_PITCH", "1.0"))     # 계획 격자 pitch
CHARGE_STEP_X = float(os.environ.get("CHARGE_STEP_X", "2.4"))
CHARGE_STEP_Y = float(os.environ.get("CHARGE_STEP_Y", "2.4"))


def charge_slots(rect=None, lat=None, step_x=None, step_y=None):
    """존 사각형 → 셀 중심 위의 슬롯. **아래 행 좌→우, 그다음 위 행** 순서.

    셀 중심은 `make_geom` 의 origin 규약대로 `lat/2 + lat*k` 다. 슬롯을 그 위에
    직접 만들므로 `_cell_of` 가 스냅해도 값이 변하지 않는다 — 간격이 정확히
    유지되는 유일한 방법이다.

    ★ x 간격은 lat 의 2배 이상이어야 한다. PIBT 는 2셀 점유를 쓰고 헤딩이
      서쪽이므로 로봇이 (r,c) 와 (r,c-1) 을 함께 쓴다. 1셀 간격이면 겹친다.
    """
    x0, y0, x1, y1 = rect or CHARGE_RECT
    lat = lat or CHARGE_LAT
    sx = step_x if step_x is not None else CHARGE_STEP_X
    sy = step_y if step_y is not None else CHARGE_STEP_Y
    org = lat / 2.0

    kx = max(1, int(round(sx / lat)))
    ky = max(1, int(round(sy / lat)))
    if kx < 2:
        raise SystemExit(
            f"★ CHARGE_STEP_X={sx} 는 pitch({lat}) 의 2배 이상이어야 합니다.\n"
            f"  PIBT 는 2셀 점유(헤딩 서쪽)라 1셀 간격이면 로봇끼리 겹칩니다.")

    def lat_ks(a, b):
        k0 = int(-((-(a - org)) // lat))              # ceil, 정수 연산
        k1 = int((b - org) // lat)
        return list(range(k0, k1 + 1))

    xs = [org + lat * k for k in lat_ks(x0, x1)][::kx]
    ys = [org + lat * k for k in lat_ks(y0, y1)][::ky]
    return [(round(x, 3), round(y, 3)) for y in ys for x in xs]


CHARGE_ZONE_LEGACY = [(105.5, y) for y in (50, 53, 56, 59, 62, 65)] + \
                     [(107.8, y) for y in (50, 53, 56, 59, 62, 65)]


def charge_zone(lat=None):
    """충전존 슬롯 — **호출 시점에** 격자를 받아 만든다.

    ★ 예전에는 `CHARGE_ZONE` 을 모듈 import 시점에 `PIBT_PITCH` 로 굳혔다.
      그런데 도구들(`adg_cycles` · `goal_oscillation` 등)은 격자를 **`PITCH`**
      라는 다른 이름으로 준다. `PITCH=1.0` 만 주면 계획은 1.0 격자인데 충전존은
      1.2 격자로 만들어져 **시나리오가 조용히 달라졌다.**

          PIBT_PITCH=1.0   충전 x [103.5, 105.5, 107.5]   starts 103·105·107
          PIBT_PITCH 없음   충전 x [103.8, 106.2, 108.6]   starts 103·106·108

      2026-09-15 FMS 와 지문을 대조하다 드러났다. 양쪽 다 `PIBT_PITCH` 없이
      돌려 **같은 방식으로 틀린** 시나리오를 재현해 왔다.

      이제 `geom.pitch` 에서 받는다 — 계획과 충전존이 같은 값을 쓰므로 어긋날
      수가 없다. 이름이 둘이던 문제가 사라진다.
    """
    if os.environ.get("CHARGE_START", "auto").lower() == "legacy":
        return CHARGE_ZONE_LEGACY
    return charge_slots(lat=lat)
GOAL_CATS = ["packing", "consol", "handoff", "aisle_buf", "inbound_buf"]


def front_rule(pitch):
    """앞 칸 규칙(S15P21A106-204)을 정하고 (front_swing, front_diag) 를 돌려준다.

    왜 여기인가
    -----------
    규칙은 **스위치가 둘**이다 — 계획기 쪽 `pibt.geometry.configure(...)` 와
    `RobotGeom` 의 필드. 한쪽만 켜지면 `isaac_drive._check_front_swing` 이
    주행 전에 죽인다. 둘을 같이 정하는 자리가 없어서 지금까지 **주행 경로에서는
    규칙이 통째로 꺼진 채** 돌았다 (`geo.configure` 를 부르는 곳이 도구
    하나뿐이었다). 그 두 스위치를 여기 한 곳에서 맞춘다.

    `PIBT_FRONT_RULE`
        4      앞 2칸 + 섞임 대각 2칸  {f0, f1, mA, mB}   <- 채택한 규칙
        2      앞 2칸만               {f0, f1}
        off    규칙 없음 (대조군)
        (없음) **계획기에 이미 설정된 상태를 그대로 읽는다.** 도구가 자기
               `geo.configure(...)` 를 먼저 부르는 경우가 있어서, 그걸 덮으면
               `adg_cycles.py` 의 RULE=off 대조군이 망가진다.

    ★ 규칙은 pitch 게이팅을 받는다. 1.2 에서는 무엇을 넣든 꺼진다 (차체가
      이미 충분히 떨어져 규칙이 필요 없다). 그래서 **요청값이 아니라 계획기가
      실제로 켠 값**(`front_swing_on()`)을 읽어 돌려준다. 요청과 결과가 다르면
      한 줄 찍는다 — 켠 줄 알고 1.2 로 돌리는 것을 막기 위해서다.
    """
    try:
        import pibt.geometry as geo
    except ImportError:
        return False, False                     # 계획기 기하가 없는 환경

    want = os.environ.get("PIBT_FRONT_RULE")
    if want is not None:
        want = want.strip().lower()
        # ★★ **이미 걸린 회전 마스크를 도로 넣어 준다** (-240, 2026-09-18).
        #
        #   `geo.configure` 는 `turn_mask` 를 안 주면 **지운다**(geometry.py:91
        #   `_TURN_MASK = None if turn_mask is None else …`). 그런데 이 함수는
        #   「앞 칸 규칙」만 정하려고 부르는 자리다. 앞 칸 규칙을 물었는데
        #   **랙 마스크가 사라지는** 것은 누구도 의도한 적이 없다.
        #
        #   ☹ 실제로 당했다. `PIBT_TURN_PAIR` 의 `_pair_table()` 이 `make_geom`
        #     을 다시 부르는데(lifelong.py), 그게 **첫 `step_h` 에서 게으르게**
        #     돌아 `setup_lifelong` 이 건 마스크를 지웠다. 로그에는
        #
        #         [turn_sweep] ★ 계획기에 걸었다 — 회전 2,976건 금지
        #         [scene] 앞 칸 규칙 PIBT_FRONT_RULE=4 -> 4칸     <- 이게 뒤에 온다
        #
        #     둘 다 찍히고 아무 경고도 없었다. 그 판에서 `A11#11
        #     turn(66,105,0)->(66,105,3)`(기하 침투 58.1 mm)이 그대로 나와
        #     랙에 10.6 mm 박혔다 — 마스크가 금지하는 회전이다.
        #
        #   `setup_lifelong` 이 「순서가 뒤집히면 configure 가 _TURN_MASK 를
        #   None 으로 되돌린다」고 **주석으로 경고**해 두었는데, 경고만으로는
        #   못 막았다. 순서를 지키라고 부탁하는 대신 **순서에 안 걸리게** 한다.
        geo.configure(turn_mask=geo.turn_mask(),
                      front_swing=(want not in ("off", "0", "no", "")),
                      front_diag=(want == "4"),
                      robot_dims=(GEOM_KW["front_len"], GEOM_KW["rear_len"],
                                  GEOM_KW["width"]),
                      pitch=pitch)
    on, diag = bool(geo.front_swing_on()), bool(geo.front_diag_on())
    if want is not None:
        if diag:
            got = "4칸"
        elif on:
            got = "앞2칸"
        else:
            got = "꺼짐"
        note = ""
        if want not in ("off", "0", "no", "") and not on:
            note = f"  ★ pitch {pitch} 는 게이팅 구간이라 규칙이 꺼졌습니다"
        print(f"[scene] 앞 칸 규칙 PIBT_FRONT_RULE={want} -> {got}{note}")
    return on, diag


def make_geom(pitch):
    """우리 로봇 기하 + 격자. origin 은 셀 (0,0) **중심**의 world 좌표."""
    on, diag = front_rule(pitch)
    return RobotGeom(pitch=pitch, origin=(pitch / 2.0, pitch / 2.0),
                     front_swing=on, front_diag=diag, **GEOM_KW)


def _pick(map_dir, *names):
    for n in names:
        p = os.path.join(map_dir, n)
        if os.path.isfile(p):
            return p
    raise SystemExit(f"맵 파일을 찾을 수 없습니다: {map_dir} 에서 {names}")


#: ★★ 풀링 방식 (-240, 2026-09-20). 기본은 종전대로 **cross**.
#
#   ☹ `cross` 는 10x10 픽셀 블록을 **십자로만** 표본한다. 그래서 블록을
#     **대각으로 지나가는** 벽·기둥 조각이 십자를 피해 가고, 그 칸이
#     「통행가능」으로 남는다. 실측:
#
#         cross 가 free 라고 한 칸 중 장애물 픽셀이 있는 칸  **185개** (2.1 %)
#         그중 작업 성분(1,969칸) 안                        **38개**
#
#     실제로 터졌다 (n=16, seed 103). `(58,104)` 에 장애물 픽셀 7개가 대각으로
#     늘어서 있는데 cross 는 못 봤다. agent13 의 **첫 액션**이 그 칸으로
#     들어가 차체가 **300 mm** 파고들었고, 벽·기둥은 씬에 콜라이더가 있어
#     물리적으로 막혔다. 잔차가 안 줄어 워치독이 24초에 판을 끊었다.
#
#   `strict` = 픽셀이 하나라도 있으면 막힘. **FMS `load_map` 의 max 풀링과
#   같은 뜻**이다 (아래 독스트링이 「FMS 도 같다」고 적어 두었는데, 정작
#   기본값은 그게 아니었다).
#
#       cross    free 8,919 · 작업성분 1,969 · 스테이션 57칸 · 숨은 칸 **38**
#       strict   free 8,734 · 작업성분 1,911 · 스테이션 57칸 · 숨은 칸 **0**
#
#   대가는 작업 면적 **−2.9 %**(58칸)뿐이고 **스테이션은 하나도 안 잃는다.**
#
#   ☹ 그래도 기본은 안 바꾼다 — 완주 세 판(s101·s103·s104)이 `cross` 위에서
#     섰다. 격자가 바뀌면 그 판들을 다시 떠야 한다. 재측정이 끝나면 그때 뒤집는다.
POOL = os.environ.get("PIBT_POOL", "cross").strip().lower()


def build_free(map_dir, pitch, mode=None):
    """0.1 m 마스크 -> pitch 격자의 통행가능 불리언 (r=y, c=x).

    반환 (free, k). k = pitch / 0.1 (정수여야 한다).

    `mode` 를 안 주면 `PIBT_POOL`(기본 `cross`)을 쓴다 — 위 주석 참고.
    """
    if mode is None:
        mode = POOL
    if mode != "cross":
        # ★ 기본과 다른 상태는 `verbose` 와 무관하게 **항상** 보여야 한다
        #   (트러블슈팅 (더) — `live_pibt` 가 verbose=False 로 부른다).
        print(f"[scene] ★★ 풀링 **{mode}** (기본 cross 아님) — PIBT_POOL", flush=True)
    k = round(pitch / 0.1)
    if abs(k * 0.1 - pitch) > 1e-9:
        raise SystemExit(f"pitch 는 0.1 m 의 배수여야 합니다: {pitch}")
    # ★ 팽창 마스크가 아니라 **원본 격자**를 쓴다 (2026-09-07, FMS 정렬)
    #
    #   obstacle_mask.npy 는 로봇 반경 0.8 m 로 이미 팽창돼 있다. 그런데 헤딩 모델은
    #   차체를 **2칸 점유 + 스윙 3칸**으로 직접 표현한다. 팽창 마스크를 쓰면 차체를
    #   두 번 세는 셈이라 3 m 통로가 통째로 막힌다.
    #
    #   실측 (FMS 공식 맵, pitch 1.2, 통로차단 ON):
    #       팽창 마스크   성분 32개, 스테이션 36곳   packing·consol·inbound 도달 불가
    #       원본 격자     성분 35개, 스테이션 51곳   전 카테고리 도달 가능
    #   앞의 것으로는 out 태스크를 집어도 내려놓을 곳이 없어 완료가 0 이었다.
    #
    #   FMS map_loader.load_map 도 같다 — `np.isin(grid01, OBSTACLE_VALUES)` 를
    #   max pooling 한다. 팽창은 안 쓴다.
    src = _pick(map_dir, "occupancy_grid.npy", "obstacle_mask.npy",
                "obstacle_mask_wallA.npy")
    g = np.load(src)
    if os.path.basename(src) == "occupancy_grid.npy":
        vals = getattr(_CFG, "OBSTACLE_VALUES", (1, 2, 5, 6)) if _CFG else (1, 2, 5, 6)
        mask = np.isin(g, vals)
    else:
        # ★ 후퇴 분기. 여기 오면 **이중 팽창**이라 통로가 막힌다.
        #   주석만 "(경고)" 라고 써 두고 아무것도 안 찍었더니, 서버에서는
        #   이중 팽창 수정이 처음부터 안 돌고 있었다 (2026-09-07, 하루 날림).
        #   로컬 map_fms 에는 원본이 있어 검증은 전부 통과했다.
        mask = g.astype(bool)
        sys.stderr.write(
            "\n[pibt_scene] ★★ occupancy_grid.npy 가 없어 **팽창본**으로 후퇴합니다.\n"
            f"   맵: {map_dir}\n"
            "   헤딩 모델은 차체를 2칸+스윙으로 직접 표현하므로 팽창본을 쓰면\n"
            "   차체를 두 번 셉니다 — 3 m 통로가 막히고 packing·consol 이\n"
            "   도달 불가가 됩니다 (완료 0 · 대기만 쌓임).\n"
            "   복원:  python deinflate_map.py <맵폴더> --write\n"
            "   확인:  python diag_reach.py <맵폴더>\n\n")
    if _CFG is not None and getattr(_CFG, "AISLE_BLOCK", False):
        mask = _CFG.apply_aisle_block(mask.copy())
    R, C = mask.shape
    r2, c2 = (R // k) * k, (C // k) * k
    blocks = (~mask[:r2, :c2]).reshape(r2 // k, k, c2 // k, k)   # True = 통행가능
    if mode == "strict":
        return blocks.all(axis=(1, 3)), k
    mid = k // 2
    if mode == "center":
        return blocks[:, mid, :, mid], k
    row_ok = blocks[:, mid, :, :].all(axis=2)      # 중앙 행 전체
    col_ok = blocks[:, :, :, mid].all(axis=1)      # 중앙 열 전체
    return row_ok & col_ok, k


def keep_station_component(free, geom, map_dir):
    """**스테이션이 가장 많이 붙은** 4연결 성분만 남긴다.

    [왜 필요한가]
    1.2 m 격자를 cross 풀링으로 만들면 창고 바깥 둘레·설비 틈새 같은 자투리가
    통행가능으로 남아 그래프가 **조각난다.** 실측 (2026-09-07, FMS 공식 맵):

        성분 32개, 상위 [3175, 1186, 350, 217, 35]   ← 최대 성분이 전체의 62%

    로봇과 목표가 서로 다른 조각에 배정되면 PIBT 는 영원히 못 간다. 24시드가
    전부 정체한 원인이 이것이었다 — 알고리즘이 아니라 **격자 전처리**다.

    WPPL 쪽 `lattice.interior()` 가 하는 일과 같다. FMS `load_map` 은 1 m
    max pooling 이라 애초에 이 문제가 없다.
    """
    R, C = free.shape
    comp = -np.ones(free.shape, dtype=np.int32)
    groups = []
    for r0 in range(R):
        for c0 in range(C):
            if not free[r0, c0] or comp[r0, c0] >= 0:
                continue
            cid = len(groups)
            stack, cells = [(r0, c0)], []
            comp[r0, c0] = cid
            while stack:
                r, c = stack.pop()
                cells.append((r, c))
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < R and 0 <= cc < C and free[rr, cc] and comp[rr, cc] < 0:
                        comp[rr, cc] = cid
                        stack.append((rr, cc))
            groups.append(cells)

    # 스테이션이 가장 많이 닿는 성분을 실내로 본다. **크기로 고르면 안 된다** —
    # 창고 바깥 둘레가 실내보다 큰 성분이 되는 경우가 있다 (2026-09-07 실측:
    # 최대 성분 3175칸을 남겼더니 스테이션이 하나도 안 들어와 전 시드 정체).
    hit = {}
    for pts in load_stations(map_dir).values():
        if not isinstance(pts, list):
            continue
        for p in pts:
            if not (isinstance(p, (list, tuple)) and len(p) == 2):
                continue
            r, c = _cell_of(geom, p[0], p[1])
            if 0 <= r < R and 0 <= c < C and comp[r, c] >= 0:
                hit[comp[r, c]] = hit.get(comp[r, c], 0) + 1
    if not hit:
        raise SystemExit("★ 어느 성분에도 스테이션이 없습니다 — 격자/좌표계 확인")
    cid = max(hit, key=hit.get)
    out = np.zeros_like(free)
    for r, c in groups[cid]:
        out[r, c] = True
    return out, len(groups), hit[cid]


def load_stations(map_dir):
    with open(_pick(map_dir, "stations.json", "stations_wallA.json"),
              encoding="utf-8") as f:
        return json.load(f)


def _cell_of(geom, x, y):
    return geom.world_to_cell(x, y)


def _first_valid_heading(free, cell, prefer=None):
    """이 칸에서 valid 한 헤딩 하나. 없으면 None."""
    order = list(prefer or []) + [h for h in range(4) if h not in (prefer or [])]
    for h in order:
        if valid_state(free, (cell[0], cell[1], h)):
            return h
    return None


def station_cells(free, geom, map_dir, cats=None):
    """{카테고리: [(r,c)...]} — lifelong 스트림이 목표를 뽑을 후보.

    `free` 밖이거나 valid 한 헤딩이 하나도 없는 칸은 뺀다. 못 서는 자리를
    목표로 주면 배차가 영원히 안 끝난다.
    """
    out = {}
    R, C = free.shape
    for cat, pts in load_stations(map_dir).items():
        if not isinstance(pts, list):
            continue
        keep = []
        for p in pts:
            if not (isinstance(p, (list, tuple)) and len(p) == 2):
                continue
            r, c = _cell_of(geom, p[0], p[1])
            if not (0 <= r < R and 0 <= c < C):
                continue
            if not free[r, c]:
                rc = _nearest_free(free, (r, c), set())
                if rc is None:
                    continue
                r, c = rc
            if _first_valid_heading(free, (r, c)) is not None and (r, c) not in keep:
                keep.append((r, c))
        if keep and (cats is None or cat in cats):
            out[cat] = keep
    return out


# [patch_charge_start2] 시작 칸 배정 — 한 곳으로 모은다 (oneshot·lifelong 공용)
#   예전에는 pick_start_goal(oneshot)과 pick_starts(lifelong)가 따로 배정해서
#   경로에 따라 결과가 달랐다. 2026-09-09 실측: lifelong 쪽이 막힌 슬롯을
#   _nearest_free 로 밀어 robot 5 가 격자 밖 (41,89) 에 섰다.
def _assign_slots(free, geom, n, verbose=True, tag="scene"):
    """CHARGE_ZONE 슬롯을 좌측 하단부터 n개 배정한다.

    2패스:
      1차 — 헤딩 서쪽(3)이 valid 한 슬롯만. 충전존이 동벽이라 로봇은 창고
            안쪽을 봐야 한다. 그게 안 되는 슬롯(x 108.6 열)은 출발 직후
            불필요한 회전을 만든다 (실측: robot 2·8·11 이 h=0 이었다).
      2차 — 1차로 n 이 안 차면 헤딩 제약을 풀되 **로그로 명시**한다.

    막힌 슬롯은 `_nearest_free` 로 밀지 않고 **건너뛴다** — 밀면 간격이 깨진다.
    """
    H, W = free.shape
    zone = charge_zone(geom.pitch)          # ★ 격자는 geom 에서 받는다

    def sweep(strict):
        st, used, skipped = {}, set(), []
        for (x, y) in zone:
            if len(st) >= n:
                break
            cell = _cell_of(geom, x, y)
            if not (0 <= cell[0] < H and 0 <= cell[1] < W) \
                    or cell in used or not free[cell]:
                skipped.append((x, y, "격자 밖/점유/막힘"))
                continue
            h = _first_valid_heading(free, cell, prefer=[3, 0, 2, 1])
            if h is None:
                skipped.append((x, y, "valid 헤딩 없음 (2셀 점유 불가)"))
                continue
            if strict and h != 3:
                skipped.append((x, y, f"서쪽 헤딩 불가 (h={h})"))
                continue
            used.add(cell)
            st[len(st)] = (cell[0], cell[1], h)
        return st, skipped

    starts, skipped = sweep(True)
    if len(starts) < n:
        s2, sk2 = sweep(False)
        if len(s2) > len(starts):
            print(f"[{tag}] ★ 서쪽 헤딩만으로는 {len(starts)}대뿐 — 제약을 풀어 "
                  f"{len(s2)}대로 채웁니다 (출발 직후 회전이 생깁니다)")
            starts, skipped = s2, sk2
    if len(starts) < n:
        raise SystemExit(
            f"★ 충전존에 {n}대를 놓을 자리가 없습니다 — {len(starts)}대만 가능.\n"
            f"  슬롯 {len(zone)}개 중 {len(skipped)}개를 걸렀습니다:\n  "
            + "\n  ".join(f"({x:.1f},{y:.1f}) {w}" for x, y, w in skipped[:8])
            + f"\n  CHARGE_STEP_Y 를 줄이면(예: 1.2) 행이 늘어납니다. "
              f"CHARGE_STEP_X 는 pitch 의 2배 미만으로 줄일 수 없습니다.")
    if verbose:
        _xs = sorted({round(geom.cell_center(s[:2])[0], 1) for s in starts.values()})
        _ys = sorted({round(geom.cell_center(s[:2])[1], 1) for s in starts.values()})
        _hs = sorted({s[2] for s in starts.values()})
        print(f"[{tag}] 충전존 시작 {len(starts)}대 · x {_xs} · y {_ys} · h {_hs}"
              + (f" · 건너뜀 {len(skipped)}" if skipped else ""))
    return starts


def pick_start_goal(free, geom, n, map_dir, seed=0, verbose=True):
    """충전존에서 출발해 작업 스테이션 하나로 가는 (starts, goals).

    **같은 시드면 언제나 같은 결과**다 — 로컬에서 뽑은 starts.json 과
    서버 러너의 계획이 일치해야 하므로 이 성질이 필수다.
    """
    rng = random.Random(seed)
    H, W = free.shape

    # [patch_charge_start] 시작: 충전존 슬롯을 좌측 하단부터, 막힌 것은 **건너뛴다**
    #   예전에는 막힌 슬롯을 `_nearest_free` 로 옆으로 밀었다. 그러면 자리는
    #   찾지만 **간격이 깨진다.** 기둥(x=104.1 · y 56~58)이 걸리는 슬롯은
    #   비우고 다음 슬롯으로 간다 — 순서는 규칙적이고 자리만 빈다.
    #   부족하면 조용히 줄이지 않고 중단한다.
    # [patch_charge_start2] 배정을 헬퍼로 (lifelong 과 같은 규칙)
    starts = _assign_slots(free, geom, n, verbose=verbose)

    # --- 목표: 작업 스테이션 중 도달 가능한 칸 ---
    st = load_stations(map_dir)
    pool = []
    for cat in GOAL_CATS:
        for (x, y) in st.get(cat, []):
            cell = _cell_of(geom, x, y)
            if 0 <= cell[0] < H and 0 <= cell[1] < W and free[cell]:
                pool.append((cat, cell))
    if not pool:
        raise SystemExit("도달 가능한 목표 스테이션이 없습니다. pitch 를 줄여보세요.")

    goals, taken = {}, set()
    for a in range(n):
        cand = [p for p in pool if p[1] not in taken] or pool
        # 시작 상태에서 실제로 도달 가능한지 거리장으로 확인한다
        rng.shuffle(cand)
        chosen = None
        for cat, cell in cand:
            d = dist_map_h(free, cell)
            if d[starts[a]] >= 0:
                chosen = (cat, cell)
                break
        if chosen is None:
            raise SystemExit(f"robot {a}: 시작 {starts[a]} 에서 도달 가능한 목표가 없습니다.")
        taken.add(chosen[1])
        goals[a] = chosen[1]
        if verbose:
            sx, sy = geom.cell_center(starts[a][:2])
            gx, gy = geom.cell_center(chosen[1])
            print(f"[scene]   robot {a}: ({sx:.1f},{sy:.1f}) h={starts[a][2]} "
                  f"-> {chosen[0]} ({gx:.1f},{gy:.1f})")
    return starts, goals


def _nearest_free(free, cell, used, max_r=12):
    H, W = free.shape
    r0, c0 = cell
    for rad in range(0, max_r):
        for dr in range(-rad, rad + 1):
            cols = (-rad, rad) if abs(dr) != rad else range(-rad, rad + 1)
            for dc in cols:
                rc = (r0 + dr, c0 + dc)
                if (0 <= rc[0] < H and 0 <= rc[1] < W and free[rc]
                        and rc not in used):
                    return rc
    return None


def starts_json(geom, starts):
    """씬 빌더(build_amr_scene_v2.py --starts)가 읽는 형식."""
    out = []
    for a in sorted(starts):
        x, y, yaw = geom.state_pose(starts[a])
        out.append(dict(id=a, x=round(x, 3), y=round(y, 3),
                        yaw_deg=round(math.degrees(yaw), 1)))
    return {"robots": out,
            "note": "pibt_core_v2 + isaac_drive. 씬 빌더는 이 좌표에 로봇을 세운다."}


def traj_json(geom, history, pitch):
    """history -> generate_wppl.py 와 같은 스키마의 trajectories.json.

    **주행에는 쓰이지 않는다.** live_pibt.py 는 ADG 로 달리고 시간표를 보지 않는다.
    이 파일이 필요한 이유는 두 가지뿐이다.
      1. build_amr_scene_v2.py 가 --traj 를 필수로 받는다 (로봇 수·초기 자세)
      2. 기존 validate.py / headless_wppl.py 로 비교해 볼 수 있다

    틱 길이는 명목값이다 — 실제로는 전진·회전이 서로 다른 시간을 쓴다.
    """
    dt = pitch / geom.v_max                      # 명목 1칸 이동 시간
    robots = {}
    for a in sorted(history[0]):
        pts = []
        for t, snap in enumerate(history):
            x, y = geom.cell_center(snap[a][:2])
            pts.append([round(t * dt, 4), round(x, 4), round(y, 4)])
        robots[str(a)] = pts
    return {"robots": robots, "meta": {
        "planner": "pibt_core_v2 run_h (heading) + isaac_drive ADG",
        "plan_cell_m": pitch, "step_time_s": round(dt, 4),
        "speed_mps": geom.v_max, "heading_offset": GEOM_KW["heading_offset"],
        "reverse_factor": _pc.REVERSE_FACTOR, "n_robots": len(robots),
        "note": "시간표는 명목값. 실제 주행은 live_pibt.py 의 ADG 가 순서로만 제어한다."}}


def pick_starts(free, geom, n, verbose=True):
    """충전존 n칸에 로봇을 세운다. **목표는 뽑지 않는다** — lifelong 은 배차가 준다."""
    # [patch_charge_start2] oneshot 과 같은 배정 규칙을 쓴다 — 경로에 따라 달라지면 안 된다
    starts = _assign_slots(free, geom, n, verbose=verbose)
    if verbose:
        for i in sorted(starts):
            print(f"[scene]   robot {i}: cell {starts[i][:2]} h={starts[i][2]}")
    return starts


def charge_docks(free, geom, n=None):
    """CHARGE_ZONE 의 world 좌표 -> 통행가능한 격자 칸. battery.py 가 쓴다.

    `pick_starts` 와 같은 `_nearest_free` 후퇴를 쓴다 — 충전존에서 출발하므로
    보통 시작 칸과 같은 칸들이 나온다.
    """
    H, W = free.shape
    zone = charge_zone(geom.pitch)          # ★ 격자는 geom 에서 받는다
    out, used = [], set()
    for (x, y) in (zone if n is None else zone[:n]):
        want = _cell_of(geom, x, y)
        cell = want if (0 <= want[0] < H and 0 <= want[1] < W
                        and free[want] and want not in used) else             _nearest_free(free, want, used)
        if cell is not None:
            used.add(cell)
            out.append(cell)
    return out


def charge_zone_cells(free, geom, rect=None):
    """충전존 사각형 안의 **통행가능 칸 전부** — lifelong 의 복귀 목표 후보.

    `charge_docks` 와는 쓰임이 다르다. 도크는 `CHARGE_ZONE` 슬롯(기본 2.4 m
    간격)만이라 12칸쯤이지만, 복귀 목표는 존 안 아무 빈 칸이나 될 수 있다.
    FMS 는 `map_loader.zone_cells(free, zone_mask)` 가 이 역할을 한다.

    순서는 FMS 와 같게 **열 오름차순 → 행 오름차순**이다. 존 서쪽(x 작은 쪽)이
    통로이므로 통로에 가까운 열이 먼저 나온다. `lifelong.zone_goal` 의 동률
    결정론이 이 순서에 달려 있다 — 바꾸면 같은 시드가 다른 결과를 낸다.

    ★ 헤딩이 하나도 서지 않는 칸은 뺀다. 2칸 점유 모델이라 존 가장자리는 뒤
      칸이 벽인 경우가 있는데, 그런 칸을 목표로 주면 거리장이 전부 -1 이라
      로봇이 TO_HOME 으로 영구 정지한다 (`station_cells` 와 같은 이유).
    """
    H, W = free.shape

    # ★★ FMS 격자에서는 **상류 함수가 만든다** (2026-09-22).
    #
    #   `charge_zone.json` 은 양쪽이 **같은 파일**이다 (102.6,48.0 -> 108.6,67.0).
    #   그런데 칸으로 옮기는 규칙이 달라 서쪽 한 열이 갈렸다.
    #
    #       FMS  c0 = int((102.6+0.4)/1.0) = 103 · mask[r0:r1, c0:c1] 끝 **배타**
    #       우리 _cell_of(102.6) = round((102.6-0.5)/1.0) = 102 · 끝 **포함**
    #
    #       -> 우리 존 125칸 · FMS 114칸. c=102 한 열(19칸)을 더 먹었다.
    #
    #   존이 넓으면 `zone_goal` 이 빈 칸을 쉽게 찾아 **덜 기다린다.** 실측으로
    #   `zone_wait_steps` 815(FMS) 대 379(우리) · `zone_retargets` 1 대 0 이었다.
    #
    #   규칙을 베껴 고치면 또 갈린다. `pibt_core_v2` 가 상류를 직접 로드해서
    #   갈릴 여지를 없앤 것과 **같은 이유**로, 여기서도 그쪽 함수를 부른다.
    if FMS_GRID and rect is None:
        import map_loader as ML
        zm = ML.load_charge_zone(free, _fms_map_dir())
        if zm is not None:
            # 순서는 FMS `map_loader.zone_cells` 와 같게 열 -> 행 오름차순.
            # ☹ `_first_valid_heading` 는 **우리 것**이다. 2칸 점유 모델이라
            #   뒤 칸이 벽인 가장자리를 목표로 주면 거리장이 전부 -1 이 되어
            #   TO_HOME 으로 영구 정지한다. FMS 는 그 모델이 없어 안 거른다.
            return [(int(r), int(c))
                    for c in range(W) for r in range(H)
                    if zm[r, c] and free[r, c]
                    and _first_valid_heading(free, (r, c)) is not None]

    x0, y0, x1, y1 = rect or CHARGE_RECT
    ra, ca = _cell_of(geom, x0, y0)
    rb, cb = _cell_of(geom, x1, y1)
    r0, r1 = min(ra, rb), max(ra, rb)
    c0, c1 = min(ca, cb), max(ca, cb)
    out = []
    for c in range(max(0, c0), min(W, c1 + 1)):
        for r in range(max(0, r0), min(H, r1 + 1)):
            if free[r, c] and _first_valid_heading(free, (r, c)) is not None:
                out.append((r, c))
    return out


#: ★★ 격자·홈·헤딩·마스크를 **FMS 것으로** 바꾼다 (S15P21A106-240, 2026-09-18).
#
#   우리 물리 판이 「FMS 이산을 물리로 증명한다」였는데, 층을 하나씩 열어 보니
#   여섯 중 셋이 우리 것이었다.
#
#       계획 코어  `pibt/` 원본 로드                  ★ 그쪽 것
#       배차       `lifelong` 이식본 (guard_flipped 0) ★ 그쪽 것 — 비트 동일 확인
#       주문       `PIBT_ORDERS` 배정표               ★ 그쪽 것 — 오늘 꽂았다
#       **격자**   `build_free` cross 풀링 · 패딩 없음  ☹ 우리 것
#       **홈**     2.4 m 물리 슬롯 · 행 우선            ☹ 우리 것 (7/12 만 겹쳤다)
#       **헤딩**   서쪽(3) 강제                         ☹ 우리 것 (FMS 는 h=0 부터)
#
#   남은 셋은 **뿌리가 하나**다 — 격자. 그쪽 격자를 쓰면 `make_homes_zone` 과
#   헤딩 규칙을 그대로 부를 수 있다.
#
#       PIBT_FMS_GRID=1    load_map · make_homes_zone · FMS 헤딩 · FMS turn_mask
#       (없음)             종전과 **비트 동일**
#
#   ☹ `CELL_M` 이 1.0 고정이라 **pitch 1.0 에 묶인다.** 그게 그쪽이 쓰는 격자다.
# ---------------------------------------------------------------------------
# FMS 격자 설정 — `sim_v2_tasks._build` 가 하는 것을 조각마다 따라간다.
#
#   ★ 아래 헬퍼들은 **`pibt_core_v2` 를 먼저 import 한 뒤에만** 부를 수 있다.
#     그것이 `3_FMS/sim_engine` 을 `sys.path` 에 넣기 때문이다. 진입점인
#     `_fms_setup` 이 맨 처음에 그걸 한다 — 순서를 바꾸면 `map_loader` 를 못 찾는다.
# ---------------------------------------------------------------------------

def _fms_map_dir():
    """FMS 공식 맵 폴더. `FMS_MAP` 으로 덮을 수 있다."""
    return os.environ.get(
        "FMS_MAP", os.path.join(os.environ["W"], "..", "..", "3_FMS", "map"))


def _fms_geom(pitch):
    """그쪽 격자에 맞춘 `RobotGeom` + 앞 칸 규칙 (on, diag).

    칸 중심이 `(c + 0.5 − OFFSET_M, r + 0.5)` 라 그 어긋남을 **origin 으로 흡수**한다.
    """
    import map_loader as ML
    if abs(ML.CELL_M - pitch) > 1e-9:
        raise SystemExit(
            f"★ PIBT_FMS_GRID 는 pitch {ML.CELL_M} 에만 쓸 수 있습니다 "
            f"(FMS map_loader.CELL_M 고정). 지금 pitch={pitch}")
    on, diag = front_rule(pitch)
    geom = RobotGeom(pitch=pitch,
                     origin=(pitch / 2.0 - ML.OFFSET_M, pitch / 2.0),
                     front_swing=on, front_diag=diag, **GEOM_KW)
    return geom, on, diag


def _fms_homes(free, st_cell, fms_map, n):
    """홈 — 그쪽 함수 그대로. 존이 없으면 고정 홈으로 떨어지는 것도 그쪽과 같다."""
    import map_loader as ML
    zm = ML.load_charge_zone(free, fms_map)
    if zm is not None:
        return ML.make_homes_zone(free, zm & free, n)
    return ML.make_homes(free, st_cell, n)


def _fms_headings(free, homes, n):
    """`kernel/core.py:_init_headings` 그대로 — h=0 부터 valid 하고 안 겹치는 첫 방향."""
    import pibt_core_v2 as _pc
    taken, starts = set(), {}
    for a in range(n):
        r0, c0 = homes[a]
        for h in range(4):
            s = (r0, c0, h)
            if _pc.valid_state(free, s) and not (set(_pc.occupied(s)) & taken):
                starts[a] = s
                taken |= set(_pc.occupied(s))
                break
        if a not in starts:
            raise SystemExit(f"★ robot{a} 홈 {homes[a]}: 유효한 초기 방향이 없습니다")
    return starts


def _fms_mask(free, fms_map, pitch, on, diag, verbose):
    """마스크도 그쪽 것 — 여유 0.05 · 0.05 m 점 표본 · 1도 간격 (M′ 이 여기서 닫힌다).

    ☹☹ **이 경로가 조용했다** (2026-09-22). 둘이 겹쳐서 났다.

      ① `live_pibt` 는 `setup_lifelong(..., verbose=False)` 로 부른다.
         그래서 아래 print 가 **실주행에서 한 번도 안 찍혔다.**
      ② `turn_sweep_mask._APPLIED` 를 안 건드렸다. `report()` 가 그걸 보므로
         **마스크가 걸렸는데도 `turn_sweep: 0`** 으로 나온다.

    그래서 로그 145판을 「`[turn_sweep] 계획기에 걸었다` 가 있나」로 훑었더니
    FMS 격자 판이 전부 「없음」으로 나왔고, **우리가 그걸 「마스크 안 걸림」으로
    읽었다.** 실제로는 그쪽 마스크가 걸려 있었다 — 구별이 안 됐다.

    `turn_sweep_mask.apply` 가 같은 이유로 이미 「verbose 와 무관하게 항상
    찍는다」로 고쳐져 있었다(-240). 이쪽만 안 따라왔다. 맞춘다.

    ☹ 금지 **건수**는 우리 경로와 기준이 다르다 (그쪽은 (H,W,4,4) 전체, 우리는
      인접 헤딩 쌍만 채운다). 판끼리 비교할 때는 **비율**을 봐야 한다.
    """
    from turn_sweep_mask import TURN_SWEEP_ON as TURN_SWEEP
    if not TURN_SWEEP:
        print("[scene] ☹ FMS 회전 마스크 **안 걸었다** (PIBT_TURN_SWEEP=0)",
              flush=True)
        return
    import map_loader as ML
    import pibt.geometry as _geo
    mask = ML.turn_mask(fms_map, ML.ROBOT_DIMS, _geo.FOOTPRINT_MARGIN_M)
    _geo.configure(turn_mask=mask, front_swing=on, front_diag=diag,
                   robot_dims=ML.ROBOT_DIMS, pitch=pitch)
    # ★ `report()` 와 로그가 같은 값을 보게 한다.
    import numpy as _np
    import turn_sweep_mask as _TSM
    _TSM._APPLIED = int((~_np.asarray(mask)).sum())
    try:
        ratio = f" · 금지 비율 {ML.masked_turn_ratio(free, mask) * 100:.2f} %"
    except Exception as e:                      # 비율을 못 재도 걸린 것은 걸린 것
        ratio = f" · 비율 못 쟀다: {e!r}"
    # ★ `verbose` 와 무관하게 **항상** 찍는다 — 위 머리말이 이유다.
    print(f"[scene] ★★ FMS 회전 마스크를 걸었다 — 회전 {_TSM._APPLIED:,}건 금지 "
          f"· 여유 {_geo.FOOTPRINT_MARGIN_M} m{ratio}", flush=True)


def _fms_stations(st_cell):
    """`{"kind[i]": (r,c)}` -> `{kind: [(r,c)]}`. **인덱스 순서를 지킨다.**"""
    import re
    cells = {}
    for name, rc in st_cell.items():
        m = re.match(r"^(.*)\[(\d+)\]$", name)
        if not m:
            continue
        cells.setdefault(m.group(1), []).append((int(m.group(2)), tuple(rc)))
    return {k: [rc for _i, rc in sorted(v)] for k, v in cells.items()}


def _fms_contact(geom, map_dir_for_contact, verbose):
    """★★ 정적 접촉 감시 — 격자를 바꿔도 **끄면 안 된다** (L, -240).

    합불 기준이 랙을 안 보는 것이 이 판의 옵션이 아니라 **결함**이었다.
    0.1 m 마스크를 보므로 격자와 무관하지만, `geom.origin` 이 바뀌었으니
    그 geom 으로 넘긴다.
    """
    try:
        import turn_sweep_mask
        turn_sweep_mask.prepare_contact(geom, map_dir_for_contact, verbose=verbose)
    except Exception as e:                    # 감시가 주행을 죽이면 안 된다
        print(f"[static] ☹ 정적 접촉 감시 준비 실패(주행은 계속): {e!r}")


def _fms_setup(n, pitch, verbose, map_dir_for_contact=None):
    """FMS `sim_v2_tasks._build` 가 하는 것을 그대로 따라간다."""
    import pibt_core_v2 as _pc          # ★ 먼저 — 이것이 sim_engine 을 sys.path 에 넣는다
    import map_loader as ML             # noqa: F401  (위 import 뒤라야 찾는다)
    assert _pc is not None

    fms_map = _fms_map_dir()
    ab = bool(getattr(_CFG, "AISLE_BLOCK", False)) if _CFG else False
    free, st_cell, _stations = ML.load_map(fms_map, aisle_block=ab)

    geom, on, diag = _fms_geom(pitch)
    homes = _fms_homes(free, st_cell, fms_map, n)
    starts = _fms_headings(free, homes, n)
    _fms_mask(free, fms_map, pitch, on, diag, verbose)
    cells = _fms_stations(st_cell)
    _fms_contact(geom, map_dir_for_contact, verbose)

    if verbose:
        print(f"[scene] ★★ **FMS 격자** {free.shape} (max 풀링 · OFFSET {ML.OFFSET_M} m)"
              f" · 통행 {int(free.sum()):,}칸 · 통로차단 {ab}")
        print(f"[scene] ★★ **FMS 홈** {n}대 · 헤딩 "
              + " ".join(str(starts[a][2]) for a in range(n)))
    return geom, free, starts, cells


def setup_lifelong(map_dir, n, pitch, seed, mode=None, verbose=True):
    """lifelong 용 진입점. 목표 대신 **스테이션 후보 집합**을 돌려준다.

    one-shot 은 로봇마다 목표를 하나 뽑아 동시에 출발시키는데, 통로차단 이후
    도달 가능한 목표가 한 줄로 쏠려 12대가 몰리고 어느 시드도 완주하지 못했다
    (2026-09-07). lifelong 은 일을 시간에 걸쳐 흘려보내므로 그 쏠림이 없다.
    """
    if FMS_GRID:
        # ★★ 격자·홈·헤딩·마스크가 전부 그쪽 것이 된다. `keep_station_component`
        #    도 안 한다 — **그쪽 격자를 그대로 쓰는 것이 이 분기의 목적**이라,
        #    우리가 한 번 더 자르면 그 순간 그쪽 격자가 아니게 된다.
        #
        #    ☹ 여기 「max 풀링이라 애초에 조각이 안 생긴다(그쪽 주석)」라고
        #      적어 두었다. **틀렸다** (2026-09-18 실측). 그런 주석은 3_FMS
        #      어디에도 없고(`grep`), 수는 이렇다 — pitch 1.0 · 같은
        #      `occupancy_grid.npy`(sha1 65ddcb0c 로 양쪽 동일):
        #
        #        FMS load_map aisle=False  free 9,333 · 성분 **61** · 상위 [4956, 2638, 565, ...]
        #        FMS load_map aisle=True   free 8,640 · 성분 **61** · 상위 [4956, 1945, 565, ...]
        #        우리 build_free(cross)    free 8,919 · 성분 **53** · 상위 [5107, 1969, 569, ...]
        #
        #      max 풀링도 조각난다. 다만 **그래서 잘라야 한다는 뜻은 아니다** —
        #      자르면 그쪽과 다른 판이 된다. 조각의 값은 따로 재서 낸다.
        return _fms_setup(n, pitch, verbose, map_dir)
    geom = make_geom(pitch)
    free, k = build_free(map_dir, pitch, mode)
    raw = int(free.sum())
    free, n_comp, n_hit = keep_station_component(free, geom, map_dir)
    if verbose:
        print(f"[scene] {geom.describe()}")
        print(f"[scene] 격자 {free.shape} ({pitch} m, {k}x {mode or POOL} 풀링)")
        print(f"[scene] 성분 {n_comp}개 중 스테이션 {n_hit}곳이 붙은 것만 사용 "
              f"({raw} -> {int(free.sum())}칸)")
    # ★★ 회전 스윕 마스크 (-240). `PIBT_TURN_SWEEP` 이 꺼져 있으면 아무것도 안 한다.
    #   여기여야 한다 — `keep_station_component` 로 `free` 가 확정된 **뒤**이고,
    #   `make_geom`(= `front_rule` -> `geo.configure`) 보다 **나중**이다.
    #   순서가 뒤집히면 `configure` 가 `_TURN_MASK` 를 None 으로 되돌린다.
    import turn_sweep_mask
    turn_sweep_mask.apply(free, geom, map_dir, verbose=verbose)
    # ★★ 정적 접촉 감시 준비 (L, -240). 마스크와 **무관하게 늘** 한다 —
    #   합불 기준이 랙을 안 보는 것이 이 판의 옵션이 아니라 결함이었다.
    try:
        turn_sweep_mask.prepare_contact(geom, map_dir, verbose=verbose)
    except Exception as e:                    # 감시가 주행을 죽이면 안 된다
        print(f"[static] ☹ 정적 접촉 감시 준비 실패(주행은 계속): {e!r}")
    starts = pick_starts(free, geom, n, verbose)
    cells = station_cells(free, geom, map_dir)
    if verbose:
        print("[scene] 스테이션 후보: "
              + ", ".join(f"{c} {len(v)}" for c, v in sorted(cells.items())))
    return geom, free, starts, cells


def setup(map_dir, n, pitch, seed, mode=None, verbose=True):
    """로컬·서버가 공통으로 부르는 진입점. 같은 인자면 같은 결과."""
    geom = make_geom(pitch)
    free, k = build_free(map_dir, pitch, mode)
    raw = int(free.sum())
    free, n_comp, n_hit = keep_station_component(free, geom, map_dir)
    if verbose:
        print(f"[scene] 성분 {n_comp}개 중 스테이션 {n_hit}곳이 붙은 것만 사용 "
              f"({raw} -> {int(free.sum())}칸)")
    if verbose:
        print(f"[scene] {geom.describe()}")
        lo, hi = geom.pitch_window
        ok = "OK" if lo < pitch < hi else "★ 범위 밖 — 2칸/스윙 모델이 안 맞는다"
        print(f"[scene] pitch {pitch} m (유효 구간 {lo:.3f} ~ {hi:.3f})  {ok}")
        print(f"[scene] 격자 {free.shape} ({pitch} m, {k}x {mode or POOL} 풀링)  "
              f"통행가능 {100*free.mean():.1f}%")
    starts, goals = pick_start_goal(free, geom, n, map_dir, seed, verbose)
    return geom, free, starts, goals


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default=os.path.join(
        here, "..", "warehouse", "map"))
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--pitch", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=9)   # 12대에서 완주 확인 (4·9·11·15·17·19·22)
    ap.add_argument("--pool", choices=("strict", "cross", "center"), default="cross")
    # ★ `..` 하나다. `here` 는 `<t3_amr>/path` 이므로 `../..` 는 t3_amr 의 **부모**
    #   (2_Simulation)로 나가 버린다 — 거기엔 v2/ 가 없다. `amr/make_path/` 쪽
    #   기본값들이 `../..` 인 것을 그대로 베껴 온 자리인데, 그쪽은 한 단계 더
    #   깊어서 같은 표기가 맞다. 인자 없이 직접 돌릴 때만 드러난다. (2026-09-11)
    ap.add_argument("--out", default=os.path.join(here, "..", "v2", "traj_pibt_h"))
    ap.add_argument("--plan", action="store_true",
                    help="계획까지 돌려 ADG 를 만들어 본다 (Isaac 불필요)")
    ap.add_argument("--max-steps", type=int, default=400)
    # --- lifelong -----------------------------------------------------------
    ap.add_argument("--lifelong", action="store_true",
                    help="주문 스트림으로 T틱 순환 (one-shot 대신)")
    ap.add_argument("--horizon", type=int, default=315,
                    help="lifelong 틱 수. 초는 격자에 딸린다 — 315틱 x (pitch/0.9) "
                         "= 350 s (pitch 1.0, 기본) / 420 s (pitch 1.2)")
    ap.add_argument("--seconds", type=float, default=None,
                    help="틱 대신 초로 지정. --clock 과 함께 쓴다")
    ap.add_argument("--clock", choices=("plan", "wall"), default="plan",
                    help="plan=계획 시간, wall=Isaac 벽시계 (stretch 1.72 적용)")
    ap.add_argument("--order-gap", type=int, default=15)
    ap.add_argument("--battery", action="store_true",
                    help="배터리·충전 도크")
    ap.add_argument("--dispatch", choices=("fms", "robot_first"), default="fms",
                    help="배차 정책. fms=태스크 순회(기본) / robot_first=로봇 순회")
    ap.add_argument("--no-zone", dest="zone", action="store_false",
                    help="충전존 복귀를 끈다 — FREED 가 시작 칸으로 돌아가던 "
                         "2026-09-11 이전 동작. 옛 기준선 재현용")
    ap.set_defaults(zone=True)
    ap.add_argument("--order-end", type=float, default=None,
                    help="업무 종료 시점. 이 뒤로는 새 주문이 없고, 남은 일을 "
                         "치운 로봇이 충전존으로 복귀한다. "
                         "1 이하면 horizon 비율(예: 0.7), 1 초과면 틱 수. "
                         "생략하면 horizon 끝까지 주문이 들어온다(이전 동작)")
    # ★ 환경변수 기본값을 **뺀다** (2026-09-17, S15P21A106-200).
    #   옛 이름 `ASSIGN` 을 기본값으로 두면, 한 번 export 하고 같은 셸에서
    #   `run_record.sh` 를 돌릴 때 **계획만** 배정표로 서고 주행은 난수로
    #   돌았다 (주행은 `live_pibt` 가 다시 계획한다). 실제로 그 함정에 걸렸다.
    #   이제 환경변수 경로는 `FMS_ASSIGN` 하나이고 `run_lifelong` 이 읽는다 —
    #   계획과 주행이 같은 문을 지나므로 갈릴 자리가 없다.
    #
    #   ★ 단 **이 인자 자체는 계획에만 걸린다.** 여기서 만든 스트림은
    #     `plan_and_build_lifelong(stream=…)` 으로 들어가는데, 주행은
    #     (`live_pibt` -> 같은 함수) 스트림을 안 넘기므로 `FMS_ASSIGN` 을 본다.
    #     그래서 `--orders` 만 주고 `FMS_ASSIGN` 을 안 주면 **계획과 주행이
    #     다른 주문으로 돈다 — 오류도 경고도 없이.** 배정표로 주행까지 하려면
    #     `FMS_ASSIGN` 을 쓴다. (224 의 옛 주석이 경고하던 자리다)
    ap.add_argument("--orders", default=None,
                    help="FMS 배정표 CSV (`packing_assign_s*.csv`). 주면 주문을 "
                         "난수로 만들지 않고 **그 파일 그대로** 읽는다 — 언제 · "
                         "어느 버퍼 · 어느 포장대가 FMS 와 같아진다. "
                         "`--seed`·`--order-gap` 은 주문에 안 쓰인다. "
                         "★ 계획 전용이다. 주행(live_pibt)은 이 파일을 안 읽고 "
                         "다시 계획하므로, 이걸로 주행까지 바꾸려 하면 둘이 "
                         "갈린다")
    args = ap.parse_args()

    map_dir = os.path.abspath(args.map)
    if args.lifelong:
        geom, free, starts, goals = setup_lifelong(
            map_dir, args.n, args.pitch, args.seed, args.pool)
    else:
        geom, free, starts, goals = setup(map_dir, args.n, args.pitch,
                                          args.seed, args.pool)

    d = os.path.join(os.path.abspath(args.out), f"fleet_{args.n:02d}")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "starts.json"), "w", encoding="utf-8") as f:
        json.dump(starts_json(geom, starts), f, ensure_ascii=False, indent=1)
    with open(os.path.join(d, "scene.json"), "w", encoding="utf-8") as f:
        json.dump(dict(n=args.n, pitch=args.pitch, seed=args.seed, pool=args.pool,
                       map=map_dir, heading_offset=GEOM_KW["heading_offset"],
                       mode="lifelong" if args.lifelong else "oneshot",
                       horizon=args.horizon, battery=bool(args.battery),
                       dispatch=args.dispatch),
                  f, ensure_ascii=False, indent=1)
    print(f"[scene] 저장: {d}")

    if args.plan:
        if args.lifelong:
            import metrics
            from isaac_drive import plan_and_build_lifelong
            horizon = args.horizon if args.seconds is None else                 metrics.horizon_for(args.seconds, geom, args.clock)
            zone = charge_zone_cells(free, geom) if args.zone else ()
            if args.zone:
                print(f"[scene] 충전존 복귀 ON · 후보 {len(zone)}칸 "
                      f"(끄려면 --no-zone)")
            # 1 이하 = horizon 비율, 1 초과 = 틱. 둘 다 받는다
            oe = args.order_end
            if oe is not None:
                oe = int(round(horizon * oe)) if oe <= 1.0 else int(round(oe))
                print(f"[scene] 업무 종료 {oe}틱 / horizon {horizon}틱 "
                      f"— 남은 {horizon - oe}틱은 복귀 시간")
            # ★ FMS 배정표를 주면 주문을 난수로 만들지 않는다. 태스크 생성이
            #   비트 단위로 같아져야 배차·주행 차이만 남는다.
            fstream = None
            if args.orders:
                from fms_stream import FileOrderStream
                fstream = FileOrderStream(args.orders, geom, free, args.map,
                                          horizon, order_end=oe)
                # ★ 단언 넷을 **여기서도** 돌린다 (2026-09-17, S15P21A106-200).
                #   `run_lifelong` 의 `FMS_ASSIGN` 경로는 `from_env()` 가
                #   `check()` 를 부르는데, 이 `--orders` 경로는 안 불렀다.
                #   같은 파일을 어느 문으로 들어오느냐에 따라 검사가 도는지가
                #   갈리면, 도는 쪽으로만 확인해 놓고 안 도는 쪽으로 돌리게 된다.
                fstream.check(strict=True)
                bad = fstream.verify()
                if bad:
                    print(f"[scene] ★ 스테이션 인덱스가 밀린 데 {len(bad)}곳 — "
                          f"{bad[:3]}")
                print(f"[scene] 주문 출처: {fstream.provenance()}")
            adg, order, history, info = plan_and_build_lifelong(
                free, starts, goals, geom, horizon=horizon, seed=args.seed,
                order_gap=args.order_gap, battery=args.battery,
                dispatch=args.dispatch, zone_cells=zone, order_end=oe,
                docks=charge_docks(free, geom) if args.battery else (),
                **({"stream": fstream} if fstream is not None else {}))
        else:
            from isaac_drive import plan_and_build
            adg, order, history, info = plan_and_build(free, starts, goals, geom,
                                                       max_steps=args.max_steps)
        print(f"[scene] {adg.summary()}")
        print(f"[scene] 액션 {info['actions']}")
        print(f"[scene] 스윕 감사 {info['sweep']}")
        if "throughput" in info:
            import metrics
            print(metrics.fmt(info["throughput"]))
            li = info["lifelong"]
            print(f"[scene] 태스크 생성 {li['tasks_spawned']} · "
                  f"완료 {li['tasks_done']} · 대기 {li['waiting']}")
            # ★ FMS `saturated_tph` 와 맞댈 값. 전체 horizon 으로 나눈 위
            #   숫자는 배정표의 빈 앞머리·꼬리 때문에 낮게 나온다 (-224).
            print(metrics.fmt_windowed(
                metrics.windowed(li.get("done_ticks"), geom,
                                 horizon=horizon)))
            # ★ 정체 로봇·틱 — FMS `standoff_ticks` 의 대안 지표 (FMS-26 §2-7).
            #   **문턱을 같이 찍는다** — 문턱이 다르면 비교가 안 되는 값인데
            #   값만 남기면 나중에 어느 문턱이었는지 못 찾는다 (FMS-28 §5 동의).
            if "stag_robot_ticks" in li:
                _cap = horizon * len(starts)
                print(f"[정체] 로봇·틱 {li['stag_robot_ticks']:,} / 상한 "
                      f"{_cap:,} = {100.0 * li['stag_robot_ticks'] / max(_cap, 1):.1f} %"
                      f"   (문턱 hd_after={li.get('hd_after')}틱 · "
                      f"목표 있는 로봇만)")
            if li.get("zone"):
                print(f"[scene] 존 복귀 대기 {li['zone_wait_steps']}틱 · "
                      f"재선택 {li['zone_retargets']}회 · "
                      f"예약무시 {li['zone_degraded']}회 · "
                      f"동시주차 최대 {li['zone_occ_max']}대")
            if li.get("battery"):
                print(f"[scene] 충전 {li['battery_charges']}회 · "
                      f"소진 {li['battery_dead_robots']}대 · "
                      f"최저 SoC {li['battery_soc_min']:.3f} · "
                      f"도크 비켜줌 {li['battery_unparked']}회")
            for w in info.get("battery_warn") or []:
                print("[scene] ★ " + w)
        with open(os.path.join(d, "trajectories.json"), "w", encoding="utf-8") as f:
            json.dump(traj_json(geom, history, args.pitch), f)
        print(f"[scene] trajectories.json 도 저장 (씬 빌더 --traj 용)")


if __name__ == "__main__":
    main()
