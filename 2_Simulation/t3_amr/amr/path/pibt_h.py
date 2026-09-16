# -*- coding: utf-8 -*-
"""pibt_core_v2(헤딩) + isaac_drive(ADG) — 시간표 없이 **순서**로 주행."""
import os
import sys

from . import default_map
from ._common import Launch, rel, run, scene_cmd as _scene


def _move_ticks():
    """전진 1칸이 몇 틱인가 — **FMS 원본에서 읽는다.**

    기동 층이라 계획기를 안 들여오지만, 이 값을 베껴 두면 상류가 바뀔 때
    `HORIZON` 과 짝이 어긋난 채 조용히 돈다. 그래서 읽어 오고, 못 읽으면
    **숫자를 지어내지 않고 예외로 죽는다** — 여기서 죽는 편이 350 s 짜리
    계획이 87.5 s 로 도는 것보다 낫다.
    """
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path_dir = os.path.join(here, "path")
    if path_dir not in sys.path:
        sys.path.insert(0, path_dir)
    import pibt_core_v2 as _pc
    return int(_pc.MOVE_TICKS)

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
# ★ 2026-09-15 (-211) 틱 모델 정합으로 315 -> 1260. 전진 1칸이 MOVE_TICKS(4)
#   틱이 되어 **틱 != 칸**이다. 계획 초는 그대로다:
#
#       전:  315틱 x (pitch/0.90)       = 350 s   (pitch 1.0)
#       후: 1260틱 x (pitch/0.90/4)     = 350 s
#
#   `tick_s` 와 **짝으로** 움직여야 한다 (path/isaac_drive.py · path/metrics.py).
#   한쪽만 바꾸면 릴리스 지평이 87.5 s 나 1,400 s 가 되고 에러는 안 난다.
HORIZON = 1260             # 틱

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
#       전원 복귀 시연:  PIBT_HORIZON=2200 PIBT_ORDER_END=1260 PIBT_ORDER_GAP=160
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
    # ★ pitch 도 셸을 먼저 본다. 아래 HORIZON 주석과 같은 이유다 — `plan` 이
    #   만드는 계획과 Isaac 이 실제로 도는 계획(live_pibt 가 in-process 로 다시
    #   세운다)이 **같은 격자여야** 한다. `run_record.sh` 가 PIBT_PITCH 기본을
    #   1.0 으로 두므로, 여기서 안 보면 `REPLAN=1` 이 1.2 로 계획해 놓고 주행은
    #   1.0 으로 도는 어긋남이 조용히 생긴다.
    pitch = float(os.environ.get("PIBT_PITCH", str(PITCH)))
    # ★ 시드도 셸을 먼저 본다 (2026-09-17). pitch·horizon 은 이미 그러는데
    #   **시드만 빠져 있었다.** 같은 이유가 그대로 적용된다 — 주행은 계획
    #   파일을 읽지 않고 `live_pibt` 가 in-process 로 다시 세우고, 그쪽은
    #   `PIBT_SEED` 를 쓴다 (`live_pibt.py:164`, 기본 9).
    #
    #       PIBT_SEED=2 REPLAN=1 bash run_record.sh
    #         계획   시드 1 (모듈 상수)  -> starts.json · 무대 스폰
    #         주행   시드 2 (PIBT_SEED)  -> 다른 시작 칸
    #
    #   스폰이 계획 시작점과 어긋나면 추종기가 자기 경로를 영영 못 잡는다
    #   (실측: robot 0 이 88.2 m 떨어져 추종오차 76 m, 420초 제자리 —
    #   `runners/build_amr_scene_v2.py` 주석). 오류는 안 난다.
    #
    #   `--seed` 인자가 오면 그게 이긴다 (명시가 환경변수보다 강하다).
    _seed = seed if seed is not None else int(
        os.environ.get("PIBT_SEED", str(SEED)))
    argv = ["pibt_scene.py", "--n", str(n),
            "--pitch", str(pitch),
            "--seed", str(_seed),
            "--map", map_dir or default_map(), "--out", rel(OUT), "--plan"]
    if MODE == "lifelong":
        argv += ["--lifelong"]
        # `seconds` 가 드디어 쓰인다. 다만 **어느 초인지**를 정해야 한다.
        #   --clock plan : 계획 시간 (FMS 틱과 같은 단위). pitch 1.0 이면 350 s = 315틱
        #   --clock wall : Isaac 벽시계. stretch 를 곱한다 (metrics.STRETCH_MEASURED)
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
        argv += ["--order-gap", os.environ.get("PIBT_ORDER_GAP", "60")]
        _oe = os.environ.get("PIBT_ORDER_END", "").strip()
        if _oe:
            argv += ["--order-end", _oe]
    out = run(argv + (extra or []))
    # ★ 이 note 는 주석이 아니라 **밖으로 나가는 값**이다. 예전에는 「계획 420 s ·
    #   x1.72 = 722 s」가 박혀 있었는데, 그건 pitch 1.2 시절 값이라 기본이 1.0 이
    #   된 뒤로 계속 틀린 숫자를 뱉고 있었다 (실제로는 350 s). 격자에서 파생시킨다.
    horizon = int(os.environ.get("PIBT_HORIZON", str(HORIZON)))
    mt = _move_ticks()
    plan_s = horizon * pitch / (0.90 * mt)           # 0.90 = 계획 속도 v_plan
    return {"out": os.path.join(rel(OUT), f"fleet_{n:02d}"), "log": out,
            # ★ 시드를 찍는다. 주행이 in-process 로 다시 계획하므로 **어느
            #   시드로 세운 계획인지**가 로그에 없으면 어긋나도 못 알아챈다.
            "note": f"{MODE} · seed {_seed} · {horizon}틱 x "
                    f"(pitch {pitch}/0.90/{mt}) = 계획 {plan_s:.0f} s "
                    f"(Isaac 벽시계는 stretch 를 곱한다 — metrics.STRETCH_MEASURED)"}


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
    # ★ 이 목록은 Isaac 프로세스 환경을 **덮어쓰는 것**이지 통째로 정하는 것이
    #   아니다. `main.py:155` 가 이렇게 띄운다.
    #
    #       os.execvpe(argv[0], argv, dict(os.environ, **env))
    #
    #   즉 **셸 환경 전체를 깔고 그 위에 이 목록을 얹는다.**
    #
    #       목록에 **있는** 이름   여기 값이 이긴다 (셸 값이 무시된다)
    #       목록에 **없는** 이름   셸에서 **그대로 상속된다**
    #
    #   ★ 2026-09-15 정정. 이 주석이 오래 "여기 없는 이름은 전달조차 안 된다"
    #     고 적고 있었는데 **틀렸다.** `dict(os.environ, **env)` 는 2026-09-09
    #     도입 이래 한 번도 바뀐 적이 없다. 그 서술을 믿고 "PIBT_V_EXEC 가
    #     전달 안 돼 주행이 늘 0.9 였다" 고 잘못 진단한 적이 있다 — 실제로는
    #     `PIBT_V_EXEC=2.2 bash run_record.sh` 가 계속 먹고 있었다.
    #
    #   2026-09-11 의 `PIBT_HORIZON=550` 이 안 먹은 것은 **덮어쓰기** 때문이
    #   맞다 (그때는 `("PIBT_HORIZON", str(HORIZON))` 로 하드코딩돼 있었다).
    #   같이 적혀 있던 ORDER_END·ORDER_GAP 의 "전달조차 안 됐다" 는 진단은
    #   위 정정에 비추어 다시 봐야 한다.
    #
    #   그래서 여기 넣는 이유는 «전달» 이 아니라 **기본값을 정하기 위해서**다.
    #   셸이 안 줬을 때 무엇이 되는지를 이 목록이 정한다.
    #   `_e` 는 셸 값을 먼저 보고 없을 때만 모듈 상수를 쓴다.
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
             _e("PIBT_ORDER_GAP", "60"),
             # 앞 칸 규칙 (-204). `pibt_scene.front_rule()` 이 읽어 계획기와
             # RobotGeom 두 스위치를 함께 맞춘다. 이 줄이 없으면 셸에서 줘도
             # Isaac 까지 **전달되지 않는다** (위 설명).
             #   4 = 앞2칸 + 섞임대각2칸 · 2 = 앞2칸 · off = 규칙 없음
             # ★ pitch 1.2 는 게이팅 구간이라 무엇을 넣든 꺼진다. 기본값을 4 로
             #   둬도 1.2 주행의 동작은 바뀌지 않고, 1.0/1.1 에서만 켜진다.
             _e("PIBT_FRONT_RULE", "4"),
             # 실행 속도·가속. `isaac_drive.FleetController` 가 읽는다.
             #   **빈 값이면 `geom.v_max`(=계획 속도)를 쓴다.**
             #
             #   ★ 이 줄이 «전달» 을 위한 것은 아니다. 위 정정대로 목록에 없어도
             #     셸 값은 상속되므로 `PIBT_V_EXEC=2.2 bash run_record.sh` 는
             #     전부터 먹고 있었다. 여기 두는 것은 **기본값을 한 곳에 적어
             #     두기 위해서**이고, `cmds` 출력에도 같이 찍혀 무엇이 도는지
             #     보이게 하려는 것이다.
             #
             #   ★ 안 주면 실행 속도 = 계획 속도(0.9)다. 계획을 낮게 잡는 근거
             #     자체가 "실행이 더 빨라 회전 손실을 따라잡는다" 이므로, 둘이
             #     같으면 그 논리가 성립하지 않는다. 채택 속도를 정했으면
             #     **반드시 명시**할 것.
             _e("PIBT_V_EXEC", ""),
             _e("PIBT_A_EXEC", "")],
        flags=["--/rtx/post/motionblur/enabled=false"])


def run_cmd(n=12):
    return launch(n).lines()
