# -*- coding: utf-8 -*-
"""pibt_core_v2(헤딩) + isaac_drive(ADG) — 시간표 없이 **순서**로 주행."""
import os

from . import default_map
from ._common import Launch, rel, run, scene_cmd as _scene

NAME = "pibt_h"
DESC = ("PIBT 헤딩(2칸 점유·스윙 예약·후진) + ADG · 1.2 m 격자 · "
        "lifelong 주문 스트림 · 배터리/충전 도크")
DRIVE = "adg"
OUT = "v2/traj_pibt_h"
SUB = "traj_pibt_h"   # 서버 $PLAN 아래 폴더명
USD = "pibt%d.usd"
PITCH = 1.2
SEED = 1
MODE = "lifelong"          # oneshot | lifelong
# 배차 정책. fms=태스크 순회(FMS 이식본) / robot_first=로봇 순회
#
# ★ 2026-09-11: 기본값을 `robot_first` → `fms` 로 되돌렸다 (S15P21A106-200).
#
#   [왜] 3_FMS 이산 시뮬과 **정책을 같게** 두기 위해서다. 두 시뮬의 KPI 차이를
#   비교하려면 배차가 같아야 한다 — 다르면 차이가 물리 때문인지 배차 때문인지
#   가릴 수 없다. 격자(1.0 vs 1.2 m)와 목표열은 AMR 기하 제약이라 못 맞추지만,
#   정책은 맞출 수 있고 비용도 상수 하나다.
#
#   [대가 — 처리량을 잃는다] 12시드 실측 (12대·horizon 315·order_gap 15·
#   배터리 ON·존복귀 ON, 완료 태스크 수):
#
#       robot_first  175   |  fms  149      robot_first 9승 2패 1무 (+17.4%)
#
#   옛 주석은 "완료 +12.8%, 6승 1패 5무" 였는데, 맵이 FMS 정렬로 바뀌고(9/8)
#   충전존 복귀가 들어간 뒤 **차이가 더 벌어졌다.** 그걸 알고도 `fms` 를 택한
#   것이다 — 지금 목적이 성능이 아니라 이산쪽과의 대조이기 때문이다.
#
#   [되돌리는 법] 두 정책 모두 살아 있다 (dispatch.py).
#       계획   python path/pibt_scene.py ... --dispatch robot_first
#       주행   PIBT_DISPATCH=robot_first bash run_record.sh
#   시연·처리량 측정이 목적이면 `robot_first` 가 낫다.
DISPATCH = "fms"
HORIZON = 315              # 틱. 315 x (1.2/0.9) = 계획 420 s

# ★ 2026-09-11: 배터리를 껐다 (S15P21A106-200).
#
#   [왜] 충전존의 쓰임을 **"업무가 끝났다"를 보여주는 자리**로 좁혔다. SoC
#   모델·도크 예약·기회 충전은 그 목적에 필요 없고, 로봇을 중간에 빼돌려
#   "일 마치고 귀환" 그림만 흐린다. 충전존 복귀(zone_cells)는 배터리와 무관
#   하게 동작한다 — 둘은 원래 별개 장치다.
#
#   [복귀 조건이 바뀐다] 배터리를 끄고 배차를 fms 로 돌린 뒤 다시 쟀다.
#   업무 315틱 고정 · 12대 · seed 1 · 존복귀 ON, 종료 시 충전존 주차 대수:
#
#       order_gap  horizon  복귀구간   완료/생성   주차
#           15       550     235틱      26/30      4/12
#           25       550     235틱      16/16     10/12
#           40       550     235틱      14/14    **12/12**
#
#   배터리 ON·robot_first 였을 때는 order_gap 25 로 12/12 였다. 배차를 fms 로
#   맞추며 처리량이 내려가 **부하를 더 낮춰야** 전원이 돌아온다.
#
#       전원 복귀 시연:  PIBT_HORIZON=550 PIBT_ORDER_END=315 PIBT_ORDER_GAP=40
#
#   [되돌리는 법] PIBT_BATTERY=1 로 주행하면 배터리가 다시 붙는다.
#   `path/battery.py` 는 지우지 않았다 — 배터리 KPI 가 다시 필요할 수 있다.
BATTERY = False

# ★ GOOD_SEEDS 를 지웠다.
#
#   one-shot 은 "전원이 동시에 목표에 있어야 성공" 이고 PIBT 는 그 조건에서
#   완전하지 않다 — 그래서 완주하는 시드를 골라야 했다 (24시드 중 4~6개).
#   lifelong 은 그 조건이 없다. 도착하면 새 태스크를 받고 떠나므로 목표에
#   주차한 로봇이 남을 막는 상황 자체가 사라진다.
SEEDS_CHECKED = (1, 2, 4, 5, 7, 9, 11, 16, 18, 21, 22, 25)


def plan(n=12, seed=None, seconds=None, map_dir=None, extra=None):
    # 기본 시드는 모듈 상수 SEED 를 쓴다. 여기에 숫자를 또 박아 두었더니
    # `main.py plan` 이 SEED 를 바꿔도 옛 값으로 계획했다 (2026-09-07).
    argv = ["pibt_scene.py", "--n", str(n), "--pitch", str(PITCH),
            "--seed", str(SEED if seed is None else seed),
            "--map", map_dir or default_map(), "--out", rel(OUT), "--plan"]
    if MODE == "lifelong":
        argv += ["--lifelong"]
        # `seconds` 가 드디어 쓰인다. 다만 **어느 초인지**를 정해야 한다.
        #   --clock plan : 계획 시간 (FMS 틱과 같은 단위). 420 s -> 315틱
        #   --clock wall : Isaac 벽시계.  420 s -> 183틱 (stretch 1.72)
        # ★ 여기도 셸 환경변수를 먼저 본다 (2026-09-11).
        #   `main.py plan` 이 만드는 계획과 Isaac 이 실제로 도는 계획(live_pibt 가
        #   in-process 로 다시 세운다)이 **같은 설정이어야** 한다. 한쪽만 환경변수를
        #   보면 "계획은 550틱인데 주행은 315틱" 같은 어긋남이 조용히 생긴다.
        if seconds is None:
            argv += ["--horizon", os.environ.get("PIBT_HORIZON", str(HORIZON))]
        else:
            argv += ["--seconds", str(seconds), "--clock", "plan"]
        if os.environ.get("PIBT_BATTERY", "1" if BATTERY else "0") not in ("0", "", "false"):
            argv += ["--battery"]
        argv += ["--dispatch", os.environ.get("PIBT_DISPATCH", DISPATCH)]
        argv += ["--order-gap", os.environ.get("PIBT_ORDER_GAP", "15")]
        _oe = os.environ.get("PIBT_ORDER_END", "").strip()
        if _oe:
            argv += ["--order-end", _oe]
    out = run(argv + (extra or []))
    return {"out": os.path.join(rel(OUT), f"fleet_{n:02d}"), "log": out,
            "note": f"{MODE} · {HORIZON}틱 = 계획 420 s "
                    f"(Isaac 벽시계로는 x1.72 = 722 s)"}


def verify(n=12, map_dir=None):
    # 계획 단계에서 ADG 비순환을 이미 확인한다. 궤적은 명목 시간표라
    # validate.py 의 속도 검사가 의미가 없어 건너뛴다.
    print("    (pibt_h 는 plan 단계에서 ADG 비순환을 확인한다 — 별도 검증 없음)")
    return True


def scene_cmd(n=12):
    return _scene(SUB, USD % n, n)


def launch(n=12):
    # 모션블러를 끈다. (예전 주석이 "자세를 대입하는 방식이라 순간이동으로 보인다"
    #  고 적었는데 틀렸다 — live_pibt 는 joint_velocities 로 실제 PhysX 주행이다.
    #  자세 대입은 replay_wppl / render_video_wppl 쪽 얘기다. 2026-09-08 정정)
    # ★ 이 목록이 Isaac 프로세스의 환경을 **통째로 정한다.** 여기 없는 이름은
    #   셸에서 `PIBT_X=... bash run_record.sh` 로 줘도 **전달되지 않고**, 여기
    #   하드코딩한 이름은 셸 값을 **덮어쓴다**.
    #
    #   실제로 그랬다 (2026-09-11): live_pibt 에 PIBT_ORDER_END·PIBT_ORDER_GAP 을
    #   추가하고 `PIBT_HORIZON=550 PIBT_ORDER_END=315 PIBT_ORDER_GAP=40` 으로
    #   서버에서 돌렸는데, HORIZON 은 str(HORIZON)=315 에 덮이고 나머지 둘은
    #   목록에 없어 전달조차 안 됐다. 두 번 돌린 결과가 **숫자까지 동일**했다
    #   (막힘 232,859 프레임 · 완주 730.3s · 액션 1769). 로그의 "릴리스 지평
    #   419s"(=315틱)가 그 증거였다.
    #
    #   그래서 셸이 준 값을 먼저 보고, 없을 때만 모듈 상수를 쓴다.
    #   새 변수를 live_pibt 에 추가하면 **여기에도 반드시 한 줄 넣을 것.**
    def _e(name, default):
        return (name, os.environ.get(name, default))

    return Launch(
        "live_pibt.py",
        # [patch_record_n_fix] PIBT_N 을 여기서 넣는다 — `--n` 을 단일 소스로.
        #   예전에는 이 목록에 PIBT_N 이 없어서, `--n 1` 만 주면 씬은 1대인데
        #   live_pibt.py 가 기본값 12로 읽어 어긋났다 (2026-09-09).
        env=[("PIBT_N", str(n)),
             ("PIBT_STAGE", "$STAGE/" + USD % n), ("PIBT_MAP", "$MAP"),
             ("PIBT_MODE", MODE),
             _e("PIBT_SEED", str(SEED)),
             _e("PIBT_PITCH", str(PITCH)),
             _e("PIBT_HORIZON", str(HORIZON)),
             _e("PIBT_BATTERY", "1" if BATTERY else "0"),
             _e("PIBT_DISPATCH", DISPATCH),
             # 업무 종료 후 전원 충전존 복귀 (-199). 빈 값이면 live_pibt 가
             # 끈 것으로 본다 — 기본 동작은 바뀌지 않는다.
             _e("PIBT_ORDER_END", ""),
             _e("PIBT_ORDER_GAP", "15"),
             # 앞 칸 규칙 (-204). `pibt_scene.front_rule()` 이 읽어 계획기와
             # RobotGeom 두 스위치를 함께 맞춘다. 이 줄이 없으면 셸에서 줘도
             # Isaac 까지 **전달되지 않는다** (위 설명).
             #   4 = 앞2칸 + 섞임대각2칸 · 2 = 앞2칸 · off = 규칙 없음
             # ★ pitch 1.2 는 게이팅 구간이라 무엇을 넣든 꺼진다. 기본값을 4 로
             #   둬도 1.2 주행의 동작은 바뀌지 않고, 1.0/1.1 에서만 켜진다.
             _e("PIBT_FRONT_RULE", "4")],
        flags=["--/rtx/post/motionblur/enabled=false"])


def run_cmd(n=12):
    return launch(n).lines()
