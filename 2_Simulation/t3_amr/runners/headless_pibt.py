# -*- coding: utf-8 -*-
"""★ PIBT/ADG 주행을 **그림 없이** 돌린다. standalone python (--exec 아님).

왜 이 파일이 필요한가
---------------------
어제 3시간짜리 판이 **벽시계 12시간**을 먹었다. 분해하면 이렇다.

    계획 3.0 h   ->   물리 6.9 h   ->   벽시계 12 h
                 2.3x (대기)        1.7x (시뮬 속도)

뒤쪽 1.7 배가 **렌더 비용**이다. `STREAM=0` 은 인코딩·전송만 끄고 RTX 렌더는
계속 돌린다 (50.51 -> 27.03 ms/step 에서 멈춘다). 그런데 `live_pibt.py` 는
Kit 의 `--exec` 용이라 **렌더를 끌 자리가 없다**:

    앱이 주루프를 쥔다  ->  렌더/물리를 번갈아 돌린다
    우리는 subscribe_physics_step_events 로 물리 콜백에 얹혀 갈 뿐이다
    -> step() 을 우리가 안 부르니 render=False 를 넘길 곳이 없다

`PIBT_RENDER_EVERY` 로 렌더만 솎으려던 시도는 실패했다. `RenderingManager.set_dt`
가 **물리 텐서 뷰를 무효화**해서 주행 3초 만에 죽는다 (2026-09-21 실측:
`Failed to get root link transforms from backend`).

그래서 반대로 간다 — **앱에서 주루프를 뺏는다.** `headless_wppl.py` 가 이미
같은 방식이다 (`world.step(render=False)`, 루프에 `app.update()` 가 없다).

무엇을 새로 짰나 — **아무것도 안 짰다**
---------------------------------------
계획·ADG·probe·시작 재정렬·주행·통계는 `live_pibt.py` 것을 **그대로** 쓴다.
사본을 만들면 두 파일이 갈라지고, 갈라지는 순간 "헤드리스 결과"가 증거가 되지
못한다. 이 파일이 하는 일은 셋뿐이다.

    ① SimulationApp 을 헤드리스로 띄운다        (--exec 대신)
    ② live_pibt.py 를 이 프로세스 안에서 실행    (runpy)
    ③ 준비가 끝나면 **루프를 우리가 돈다**       (렌더 없이)

`live_pibt.py` 쪽 변경은 `PIBT_HEADLESS=1` 분기 다섯 줄이 전부다. 그 분기는
구독을 건너뛰고 `state["ready"]=True` 로 fleet 을 넘겨줄 뿐, 주행 로직을
한 줄도 바꾸지 않는다.

물리 결과는 같은가 — 같다
-------------------------
적분은 physics_dt(1/60) 단위이고 벽시계와 무관하다. 렌더를 안 그린다고
접촉 판정이 달라지지 않는다. 달라지는 건 **속도뿐**이다. 그래도 믿지 말고
재라 — 검증은 같은 시드로 돌려 네 값이 맞는지 보는 것이다.

    completed · contact_events · worst_gap · turn_body_gaveup

쓰는 법
-------
    cd <t3_amr>
    PIBT_MODE=lifelong PIBT_N=12 PIBT_PITCH=1.0 PIBT_SEED=104 \
    PIBT_HORIZON=1260 \
    PIBT_POOL=strict PIBT_ADG_BODY=1 PIBT_ADG_RANK=1 \
    PIBT_TURN_PAIR_NEXT=1 PIBT_TURN_YIELD=1 \
      python runners/headless_pibt.py 2>&1 | tee logs/hl_s104.log

`python` 은 `headless_wppl.py` 를 돌릴 때 쓰는 것과 **같은 것**이다 (서버의
python 이 곧 Isaac python 이다 — run.sh:132 참조).

☹ `isaacsim ... --exec runners/headless_pibt.py` 로 부르면 **안 된다.** 그러면
  앱이 다시 주루프를 쥐고 렌더를 돌린다 — 이 파일이 존재하는 이유가 사라진다.
  `run_record.sh` / `run.sh` 도 마찬가지다. 그쪽은 `--exec live_pibt.py` 경로다.

이 파일 전용 스위치
    PIBT_HL_DT          물리 dt          (기본 1/60 — live_pibt 와 같아야 한다)
    PIBT_HL_MAX_SIM     시뮬 시간 상한(초). 0 이면 무제한 (기본 0)
    PIBT_HL_MAX_WALL    벽시계 상한(초). 0 이면 무제한 (기본 0)
    PIBT_HL_REPORT      배속 보고 주기(스텝). 기본 600 (=10초)
    PIBT_HL_STEPPER     physx | world    (기본 physx)
    PIBT_HL_SETUP_CAP   준비 단계 프레임 상한. 기본 12000
    PIBT_HL_SHOT_RES    촬영 해상도 "1280x720" (리플리케이터 경로에서만 쓴다)

===========================================================================
촬영 — **그린 것을 버리지 않는다**
===========================================================================
`run_record.sh` 는 `PIBT_SHOT_STRIDE=20`, 즉 물리 20스텝마다 한 장을 저장한다.
그런데 Kit `--exec` 경로에서는 **렌더가 매 스텝 돈다.** 그린 것의 95%를 버린다.

여기서는 그 낭비가 없다. 기본은 아예 안 그리고, `PIBT_SHOTS` 를 주면
**저장할 그 스텝에만** 한 장 그린다.

    PIBT_SHOTS=<폴더> PIBT_SHOT_STRIDE=20  ->  렌더 호출이 1/20 로 준다

이름과 조립 공식은 `live_pibt.py` 것을 **그대로** 쓴다 (f_<sim시각 0.01s 9자리>).
배속 = STRIDE x SHOT_FPS / 60 도 그대로다.

★ 렌더는 **물리를 밀지 않는다.** `/app/player/playSimulations` 를 잠깐 꺼서
  `SimulationContext.render()` 와 같은 보호를 건다. 이게 없으면 촬영한 스텝만
  물리가 두 번 밟혀 **결과가 달라진다** — 촬영 여부로 판정이 바뀌면 안 된다.

☹ 그래도 촬영을 켜면 느려진다. 숫자만 필요하면 켜지 마라. 완전한 시연 영상은
  `PIBT_RECORD=out/rec_pibt12.npz` 로 자세만 남기고 `runners/replay_wppl.py` /
  `render_video_wppl.py` 로 따로 뽑는 쪽이 더 빠르고 배속도 사후에 고를 수 있다.
"""
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_BASE = os.path.dirname(_HERE)

# ★ SimulationApp 보다 먼저 세운다 — live_pibt.py 가 임포트 시점에 읽는다.
os.environ["PIBT_HEADLESS"] = "1"
os.environ.setdefault("AMR_BASE", _BASE)

SHOTS = (os.environ.get("PIBT_SHOTS", "") or "").strip()

# ★★ **두 번째 시점** (2026-09-22, -264). 비면 종전과 완전히 같다.
#
#   백엔드가 상단 키에서 `_side` 를 계산해 MinIO 에 있는지 확인하고 버튼을
#   띄운다. 그래서 **파일 이름만** 지키면 되고 결과 페이로드는 안 바뀐다.
#
#   ☹ 부하 — 리플리케이터 경로는 **저장할 스텝에만** 렌더한다(1/STRIDE).
#     시점이 둘이면 그 스텝에서 render product 가 둘이라 렌더가 대략 2배,
#     디스크·조립·업로드도 2배다. 다만 물리는 그대로다 — 매 스텝 도는 물리에
#     비하면 3 Hz 렌더의 2배는 작다. **실측 전이다.**
SHOTS_SIDE = (os.environ.get("PIBT_SHOTS_SIDE", "") or "").strip()
CAMERA_SIDE = (os.environ.get("PIBT_CAMERA_SIDE", "") or "").strip()
SHOT_STRIDE = max(1, int(os.environ.get("PIBT_SHOT_STRIDE", "20")))
SHOT_EXT = os.environ.get("PIBT_SHOT_EXT", "png")
SHOT_RES = (os.environ.get("PIBT_HL_SHOT_RES", "") or "1280x720").lower()

DT = float(os.environ.get("PIBT_HL_DT", "") or (1.0 / 60.0))
MAX_SIM = float(os.environ.get("PIBT_HL_MAX_SIM", "0") or 0.0)
MAX_WALL = float(os.environ.get("PIBT_HL_MAX_WALL", "0") or 0.0)
REPORT = max(1, int(os.environ.get("PIBT_HL_REPORT", "600")))
STEPPER = os.environ.get("PIBT_HL_STEPPER", "physx").strip().lower()
SETUP_CAP = int(os.environ.get("PIBT_HL_SETUP_CAP", "12000"))

# ===========================================================================
# ① 앱 기동 — 헤드리스
# ===========================================================================
from isaacsim import SimulationApp                      # noqa: E402

_CFG = {"headless": True}
# GPU 선택. `--exec` 경로에서는 Kit 플래그(--/renderer/activeGpu=$GPU)가 했는데
# 여기는 Kit 을 안 띄우므로 SimulationApp 설정으로 넘긴다. 팀원과 겹칠 때
# `GPU=1 bash run.sh ...` 가 그대로 먹어야 한다.
_gpu = (os.environ.get("GPU", "") or "").strip()
if _gpu.isdigit():
    _CFG["active_gpu"] = int(_gpu)
    _CFG["multi_gpu"] = False

print(f"[hl] SimulationApp 기동 (headless) · dt={DT:.6f} · stepper={STEPPER}"
      + (f" · GPU {_gpu}" if _gpu.isdigit() else ""))
simulation_app = SimulationApp(_CFG)

import carb                                             # noqa: E402
import omni.physx                                       # noqa: E402

# ===========================================================================
# ② live_pibt.py 를 이 프로세스 안에서 실행한다
# ===========================================================================
#   임포트가 아니라 실행이다 — live_pibt 는 모듈 최상위에서 전부 하고
#   마지막 줄이 asyncio.ensure_future(_run()) 이다. 그 코루틴은 아직 안 돈다.
import runpy                                            # noqa: E402

_LIVE = os.path.join(_HERE, "live_pibt.py")
if not os.path.isfile(_LIVE):
    print(f"[hl] ★ live_pibt.py 가 없다: {_LIVE}")
    simulation_app.close()
    sys.exit(2)

print(f"[hl] live_pibt.py 실행 -> {_LIVE}")
G = runpy.run_path(_LIVE, run_name="live_pibt_headless")

state = G["state"]
on_physics = G["_on_physics"]
quit_fn = G["_quit"]
task = state.get("task")

# --- 준비가 끝날 때까지 앱을 민다 ---
#   여기서는 렌더가 돈다. 스테이지 로딩(낱박스 1,923개) · probe · 시작 재정렬이
#   전부 프레임 수로 세는 대기라서 앱 루프가 있어야 한다. 40초쯤 걸린다.
#   **주행이 시작되면 그 뒤로는 앱을 한 번도 밀지 않는다.**
print("[hl] 준비 대기 (스테이지 로드 · 계획 · probe · 재정렬) …")
_w0 = time.time()
_frames = 0
while not state.get("ready") and not state.get("done"):
    if task is not None and task.done():
        break
    if _frames >= SETUP_CAP:
        print(f"[hl] ★ 준비가 {SETUP_CAP} 프레임 안에 안 끝났다 — 중단")
        break
    simulation_app.update()
    _frames += 1

if not state.get("ready"):
    print(f"[hl] ★ 주행에 못 들어갔다 (프레임 {_frames:,} · "
          f"{time.time() - _w0:.0f}s). 위 로그의 [pibt] 오류를 보라")
    if task is not None and task.done():
        try:
            _e = task.exception()
            if _e is not None:
                import traceback
                print("[hl] _run 예외:")
                traceback.print_exception(type(_e), _e, _e.__traceback__)
        except Exception:
            pass
    simulation_app.close()
    sys.exit(3)

fleet = state["fleet"]
print(f"[hl] 준비 완료 — 프레임 {_frames:,} · {time.time() - _w0:.0f}s. "
      + (f"여기서부터 렌더는 **{SHOT_STRIDE}스텝에 한 번**뿐" if SHOTS
         else "여기서부터 **렌더 없음**"))

# ===========================================================================
# 촬영 (선택) — 저장할 스텝에만 한 장 그린다
# ===========================================================================
#   ★ 렌더가 물리를 밀지 않게 막는다. `SimulationContext.render()` 가 쓰는 것과
#     같은 보호다 — 이게 없으면 `simulation_app.update()` 가 타임라인을 한 칸
#     밀어서, **촬영한 스텝만 물리가 두 번** 밟힌다. 그러면 촬영 여부로 접촉
#     판정이 달라진다. 그건 증거로 못 쓴다.
import carb.settings                                    # noqa: E402

_settings = carb.settings.get_settings()


def _render_once():
    _settings.set("/app/player/playSimulations", False)
    try:
        simulation_app.update()
    finally:
        _settings.set("/app/player/playSimulations", True)


# 캡처 경로는 둘이다. 뷰포트가 있으면 live_pibt 것을 그대로 쓰고(파일명·조립
# 공식이 거기 묶여 있다), 없으면 리플리케이터로 같은 이름을 쓴다.
_cap = None                 # None | "viewport" | "replicator"
_rep_annot = None
_rep_annot2 = None          # 측면. None 이면 상단만 찍는다
_shot_n, _shot_fail = 0, 0
_side_n = 0                 # 측면 장수 — 상단과 따로 센다 (경로가 다르다)
_side_fail = 0              # 측면 저장 실패 누적 (상단처럼 몇 번은 참는다)
_side_n_try = 0             # 측면 캡처 시도 횟수 — PIBT_SIDE_EVERY 주기 계산용


def _attach_side():
    """측면 카메라를 **리플리케이터로** 붙인다. 실패하면 None.

    ★ 상단 경로와 **무관하게** 돈다 (2026-09-23).
      상단이 뷰포트면 `live_pibt` 의 `capture_viewport_to_file` 이 찍고, 상단이
      리플리케이터면 `_rep_annot` 이 찍는다. 측면은 어느 쪽이든 자기 render
      product 를 갖는다 — 뷰포트는 하나뿐이라 카메라를 바꿔 끼울 수 없고,
      바꿔 끼우면 캡처가 비동기라(`live_pibt.py:497`) 엉뚱한 프레임이 찍힌다.

    ☹ 2026-09-22 에 이 함수가 **리플리케이터 분기 안에만** 있었다. 그런데 이
      서버는 뷰포트 분기로 돌아서 측면이 한 장도 안 나왔다 (`hl264c`: 상단
      6,861장 · 측면 0장). 오류도 경고도 없었다 — 백엔드가 `_side` 키를
      못 찾아 버튼만 안 생긴다.

    부하 — 실측 1.0 ms/step 이하 (촬영 ON 16.58 vs OFF 15.60, STRIDE 20).
    """
    if not (SHOTS_SIDE and CAMERA_SIDE):
        return None
    try:
        import omni.kit.app as _ka
        _ka.get_app().get_extension_manager() \
           .set_extension_enabled_immediate("omni.replicator.core", True)
        import omni.replicator.core as rep                # noqa: E402
        os.makedirs(SHOTS_SIDE, exist_ok=True)
        _w, _h = (int(x) for x in SIDE_RES.split("x"))
        annot = rep.AnnotatorRegistry.get_annotator("rgb")
        annot.attach([rep.create.render_product(CAMERA_SIDE, (_w, _h))])
        print(f"[hl] 촬영 ON (2번영상) {SHOTS_SIDE} · 카메라 {CAMERA_SIDE} · {_w}x{_h}"
              + (" · 고정" if SIDE_FOLLOW < 0 else
                 f" · 로봇 {'auto' if SIDE_AUTO else SIDE_FOLLOW} "
                 + (f"3인칭 {SIDE_DIST:g}m" if SIDE_VIEW == "chase"
                    else f"**1인칭** 앞 {SIDE_FWD:g}m · 높이 {SIDE_EYE_Z:g}m"
                       f" · 초점 {SIDE_FOCAL:g}mm"))
              + (f" · {SIDE_EVERY}번에 한 번" if SIDE_EVERY > 1 else ""))
        return annot
    except Exception as e:                                # noqa: BLE001
        print(f"[hl] ☹ 2번영상을 못 켠다 — 1번만 찍는다: {e!r}")
        return None


SIDE_FAIL_MAX = int(os.environ.get("PIBT_SIDE_FAIL_MAX", "") or 20)

# ★★ 측면은 **AMR 한 대를 대각선 뒤에서** 잡는다 (2026-09-23).
#
#   처음엔 `Cam_Overview`(창고 전체 조망)를 썼는데 요청은 「한 대의 대각 측면」
#   이었다. 조망으로는 1.5 m 짜리 AMR 이 점이라 선반의 상자가 안 보인다.
#
#   고정 카메라(`Cam_Spot`)로는 **로봇이 그 자리를 지날 때만** 잡힌다 — 빈
#   통로가 찍힌 영상이 백엔드로 올라갈 수 있다. 그래서 매 캡처마다 카메라를
#   대상 로봇 뒤로 옮긴다.
#
#       PIBT_SIDE_FOLLOW   auto(기본) | 로봇 번호 | -1(카메라 고정)
#       PIBT_SIDE_VIEW     fpv(기본) | chase
#       PIBT_SIDE_DIST     chase 일 때 거리 [m]
#       PIBT_SIDE_SIDE     chase 일 때 좌/우  (-1 왼쪽 · +1 오른쪽)
#
#   ★ 기본은 **1인칭**이다 (2026-09-23). 3인칭 추종(chase)은 카메라가 창고를
#     넓게 담아 렌더가 무겁다. 1인칭은 통로 앞만 보므로 화면에 드는 기하가
#     훨씬 적다. 주행 방향이 그대로 보여 시연에도 읽기 쉽다.
#
#     ☹ 복사 비용은 **안 줄어든다** — 텍스처를 호스트로 옮기는 몫은 픽셀 수에만
#       달렸다. 줄이려면 `PIBT_SIDE_RES` 를 내리거나 `PIBT_SIDE_EVERY` 를 올린다.
# ★ 기본은 **auto** — 초반에 가장 많이 움직인 로봇을 고른다 (2026-09-23).
#   0번은 충전존에서 시작해 한참 서 있는 일이 잦아 영상이 심심했다. 어느 번호가
#   바쁜지는 시드·궤적마다 달라서 손으로 고르면 매번 빗나간다.
#       PIBT_SIDE_FOLLOW=auto  (기본)  ·  =5 특정 로봇  ·  =-1 카메라 고정
_sf = (os.environ.get("PIBT_SIDE_FOLLOW", "") or "auto").strip().lower()
SIDE_AUTO = (_sf == "auto")
SIDE_FOLLOW = 0 if SIDE_AUTO else (int(_sf) if _sf.lstrip("-").isdigit() else 0)
# 이만큼 캡처한 뒤 고른다. STRIDE 40 이면 15회 = 물리 600스텝 = 시뮬 10초.
SIDE_AUTO_AFTER = max(1, int(os.environ.get("PIBT_SIDE_AUTO_AFTER", "") or 15))
SIDE_VIEW = (os.environ.get("PIBT_SIDE_VIEW", "") or "fpv").strip().lower()
SIDE_DIST = float(os.environ.get("PIBT_SIDE_DIST", "") or 6.0)
SIDE_LR = 1.0 if (os.environ.get("PIBT_SIDE_SIDE", "") or "-1").strip() != "-1" else -1.0
# ★ 1인칭 눈 위치 — **차 앞면보다 앞**이어야 한다.
#   구동축이 앞이라(heading_offset=0) 차체는 뒤로 뻗지만, 선반은 축 앞으로도
#   0.39 m 나오고 z 0.22~1.65 를 채운다. 축 바로 위에 두면 카메라가 **선반
#   구조물 안**에 들어가 포스트와 데크만 보인다.
#   축에서 앞으로 0.55 m · 높이 1.20 m 가 기본 — 차 앞머리에 단 대시캠 자리다.
SIDE_FWD = float(os.environ.get("PIBT_SIDE_FWD", "") or 0.55)
SIDE_EYE_Z = float(os.environ.get("PIBT_SIDE_EYE_Z", "") or 1.20)
# 겨냥점을 앞으로 이만큼, 바닥 쪽으로 내려 본다 — 통로와 앞차가 같이 들어온다.
SIDE_LOOK = float(os.environ.get("PIBT_SIDE_LOOK", "") or 12.0)
SIDE_LOOK_Z = float(os.environ.get("PIBT_SIDE_LOOK_Z", "") or 0.60)
# 측면을 **몇 번에 한 번** 찍나. 1 이면 상단과 같은 주기.
#   렉이 심하면 이것을 올린다 — 비용이 그만큼 나뉜다. 대신 측면 영상이 그 배수만큼
#   빨라진다 (상단 10배속 · EVERY=3 이면 측면 30배속).
SIDE_EVERY = max(1, int(os.environ.get("PIBT_SIDE_EVERY", "") or 1))
# 근접 화면이라 조망만큼 클 필요가 없다. **복사량이 곧 비용**이다 —
# 리플리케이터는 텍스처를 호스트로 직접 복사하고(Kit 이 그렇게 경고한다),
# 1280x720 두 시점이 28 ms/step(배속 0.60)이었다.
SIDE_RES = (os.environ.get("PIBT_SIDE_RES", "") or "960x540").lower()
_side_cam_warned = False
_side_xop = None            # 카메라 transform op — 한 번만 만들고 값만 갱신한다
# ★ 초점거리 [mm]. 씬의 `Cam_Spot` 은 **24 mm 광각**으로 만들어져 있다
#   (`build_amr_scene_v2.py:308`). 눈높이 1.2 m 에서 화각 47도면 아래쪽이 4 m 앞
#   바닥을 잡아 **하단 절반이 바닥**이 된다. 주행 화면으로는 35 mm 쯤이 낫다.
#     24 mm -> 화각 47.0도    35 mm -> 33.5도    50 mm -> 23.7도
SIDE_FOCAL = float(os.environ.get("PIBT_SIDE_FOCAL", "") or 35.0)
_side_cam_n = 0             # 카메라를 옮긴 횟수 (로그용)
_side_pick = None           # auto 로 고른 로봇 (한 번 고르면 안 바꾼다)
_side_home = None           # 각 로봇의 시작 자리 — 움직인 거리를 재는 기준


def _side_track(fleet_):
    """측면 카메라를 대상 로봇에 붙인다 — 기본은 **1인칭 주행 시점**.

    실패해도 주행을 죽이지 않는다 — 한 번만 알리고 그 뒤로 조용히 넘어간다.
    카메라가 안 움직이면 마지막 자리에 머물 뿐이다.
    """
    global _side_cam_warned, _side_pick, _side_home, _side_xop, _side_cam_n
    if (not SIDE_AUTO and SIDE_FOLLOW < 0) or _rep_annot2 is None or not CAMERA_SIDE:
        return
    try:
        import math as _m
        # ★ auto — 초반에 **가장 많이 움직인** 로봇을 골라 그 뒤로 고정한다.
        #   고르는 동안은 SIDE_FOLLOW(기본 0)를 따라간다. 한 번만 갈아탄다 —
        #   매 프레임 갈아타면 화면이 튄다.
        who = SIDE_FOLLOW
        if SIDE_AUTO:
            if _side_pick is not None:
                who = _side_pick
            else:
                n_rb = len(fleet_.drivers)
                poses = [fleet_.drivers[i].axle_pose() for i in range(n_rb)]
                if _side_home is None:
                    _side_home = [(p[0], p[1]) for p in poses]
                if _side_cam_n >= SIDE_AUTO_AFTER:
                    moved = [_m.hypot(p[0] - h[0], p[1] - h[1])
                             for p, h in zip(poses, _side_home)]
                    _side_pick = max(range(n_rb), key=lambda i: moved[i])
                    who = _side_pick
                    print(f"[hl]   [cam] ★ 로봇 {_side_pick} 를 따라간다 "
                          f"(시뮬 초반에 {moved[_side_pick]:.1f} m 이동 · "
                          f"가만히 있던 대수 {sum(1 for d in moved if d < 0.2)})",
                          flush=True)
        drv = fleet_.drivers[who]
        x, y, yaw = drv.axle_pose()
        from pxr import Gf, UsdGeom                      # noqa: E402
        import omni.usd                                  # noqa: E402
        fx, fy = _m.cos(yaw), _m.sin(yaw)
        if SIDE_VIEW == "chase":
            # 3인칭 — 뒤로 0.75d, 옆으로 0.5d, 높이 0.55d
            d = SIDE_DIST
            eye = Gf.Vec3d(x - 0.75*d*fx - 0.5*d*(-fy)*SIDE_LR,
                           y - 0.75*d*fy - 0.5*d*(fx)*SIDE_LR, 0.55*d)
            tgt = Gf.Vec3d(x, y, 0.75)
        else:
            # ★ 1인칭 — 차 앞머리에서 주행 방향을 본다 (대시캠).
            eye = Gf.Vec3d(x + SIDE_FWD*fx, y + SIDE_FWD*fy, SIDE_EYE_Z)
            tgt = Gf.Vec3d(x + (SIDE_FWD + SIDE_LOOK)*fx,
                           y + (SIDE_FWD + SIDE_LOOK)*fy, SIDE_LOOK_Z)
        f = (tgt - eye).GetNormalized()
        r = Gf.Cross(f, Gf.Vec3d(0, 0, 1)).GetNormalized()
        u = Gf.Cross(r, f)
        # ★ transform op 은 **한 번만 만들고 값만 갱신**한다 (2026-09-23).
        #   매 프레임 `ClearXformOpOrder()` + `AddTransformOp()` 를 하면 이미
        #   있는 `xformOp:transform` 을 다시 만들려다 두 번째부터 조용히 실패할
        #   수 있다. 그러면 카메라가 **첫 자리에 그대로 멈춘다** — 영상이 한
        #   장면에서 안 바뀐다.
        if _side_xop is None:
            prim = omni.usd.get_context().get_stage().GetPrimAtPath(CAMERA_SIDE)
            if not prim or not prim.IsValid():
                raise RuntimeError(f"카메라 prim 이 없다: {CAMERA_SIDE}")
            # 초점거리도 여기서 한 번 잡는다 — 씬 기본(24 mm)은 주행 화면에 너무 넓다.
            try:
                UsdGeom.Camera(prim).GetFocalLengthAttr().Set(SIDE_FOCAL)
            except Exception as _fe:                     # noqa: BLE001
                print(f"[hl]   [cam] 초점거리를 못 바꿨다 (씬 기본 그대로): {_fe!r}")
            xf = UsdGeom.Xformable(prim)
            xf.ClearXformOpOrder()
            _side_xop = xf.AddTransformOp()
        _side_xop.Set(Gf.Matrix4d(
            r[0], r[1], r[2], 0, u[0], u[1], u[2], 0,
            -f[0], -f[1], -f[2], 0, eye[0], eye[1], eye[2], 1))
        # 움직이는지 로그로 보이게 한다 — 안 움직이면 여기 좌표가 그대로다.
        if _side_cam_n < 3 or _side_cam_n % 100 == 0:
            print(f"[hl]   [cam] #{_side_cam_n} 로봇{who} ({x:.2f}, {y:.2f}, "
                  f"{_m.degrees(yaw):.0f}deg) -> 눈 ({eye[0]:.2f}, {eye[1]:.2f}, "
                  f"{eye[2]:.2f})", flush=True)
        _side_cam_n += 1
    except Exception as e:                               # noqa: BLE001
        if not _side_cam_warned:
            _side_cam_warned = True
            print(f"[hl] ☹ 1인칭 카메라 추종 실패 — 고정 화각으로 간다: {e!r}")


def _save_side(sim_t):
    """측면 한 장. 실패가 `SIDE_FAIL_MAX` 회 쌓이면 **측면만** 끈다.

    ☹ 2026-09-23: 처음엔 **첫 실패에 바로 껐다.** 그런데 리플리케이터
      annotator 는 render product 를 붙인 직후 몇 프레임 동안 버퍼가 비어 있고
      (`rgb 버퍼가 비었다`), 그 한 번에 측면이 영영 꺼졌다 — `side1` 실측에서
      「촬영 ON (측면)」이 찍혔는데도 0 장이 나온 이유다.

      상단 경로는 같은 상황을 이미 관용한다 — `live_pibt._shot` 이 20회까지
      참고 그제서야 끈다. **같은 관용으로 맞춘다.**

    ★ 여기서 20회를 다 쓰고도 안 되면 그건 지연이 아니라 **구조 문제**다
      (뷰포트가 있는 판에서 리플리케이터가 데이터를 못 받는 것). 그때는 마지막
      줄이 그렇게 말하므로 다음 판을 안 태우고 바로 안다.
    """
    global _rep_annot2, _side_n, _side_fail
    if _rep_annot2 is None:
        return
    try:
        _save_one(_rep_annot2, SHOTS_SIDE, sim_t)
        _side_n += 1
    except Exception as e:                                # noqa: BLE001
        _side_fail += 1
        if _side_fail <= 3:
            print(f"[hl] 2번영상 저장 실패 {_side_fail}회 (계속 시도): {e!r}")
        if _side_fail >= SIDE_FAIL_MAX:
            print(f"[hl] ☹ 2번영상 저장이 {SIDE_FAIL_MAX}회 실패 — 2번영상을 끈다. "
                  f"마지막: {e!r}")
            if _side_n == 0:
                print("[hl]   ★ 한 장도 못 받았다 = 지연이 아니라 구조 문제다. "
                      "뷰포트가 있는 판에서는 리플리케이터 대신 **두 번째 "
                      "뷰포트**(create_viewport_window + capture_viewport_to_file, "
                      "상단이 쓰는 그 API)로 가야 한다.")
            _rep_annot2 = None

if SHOTS:
    os.makedirs(SHOTS, exist_ok=True)
    if state.get("vp") is not None:
        _cap = "viewport"
        print(f"[hl] 촬영 ON (뷰포트) {SHOTS} · {SHOT_STRIDE}스텝마다 .{SHOT_EXT}")
    else:
        # 헤드리스 experience 에는 활성 뷰포트가 없을 수 있다. 그때는 카메라에
        # render product 를 직접 걸어 rgb 를 받는다 (합성데이터 표준 경로).
        try:
            import omni.kit.app as _ka
            _ka.get_app().get_extension_manager() \
               .set_extension_enabled_immediate("omni.replicator.core", True)
            import omni.replicator.core as rep          # noqa: E402
            _cam = os.environ.get("PIBT_CAMERA", "/World/Cameras/Cam_Top")
            _w, _h = (int(x) for x in SHOT_RES.split("x"))
            _rp = rep.create.render_product(_cam, (_w, _h))
            _rep_annot = rep.AnnotatorRegistry.get_annotator("rgb")
            _rep_annot.attach([_rp])
            _render_once()                  # 첫 프레임에서 버퍼가 생긴다
            _cap = "replicator"
            print(f"[hl] 촬영 ON (리플리케이터) {SHOTS} · {SHOT_STRIDE}스텝마다 "
                  f".{SHOT_EXT} · {_w}x{_h} · 카메라 {_cam}")
        except Exception as e:
            print(f"[hl] ★ 촬영을 켤 수 없다 — 끄고 주행만 한다: {e!r}")
            print("[hl]   영상은 PIBT_RECORD=<npz> + runners/replay_wppl.py 쪽이")
            print("[hl]   더 빠르고 배속도 사후에 고를 수 있다.")
            _cap = None

# ★ 2번영상은 **1번과 독립이다** (2026-09-23). 1번을 끄고 2번만 찍는 판
#   (`CAPTURE=side`)이 있어서, `if SHOTS:` 블록 **밖**에서 붙인다.
#   1번 프레임이 13대 10분 판에 14 GB 라 시연 영상만 뽑을 때는 그게 아깝다.
if SHOTS_SIDE and CAMERA_SIDE:
    _rep_annot2 = _attach_side()
    # ★ 붙인 직후 몇 프레임을 **버린다.** annotator 는 첫 렌더에 버퍼가
    #   안 차는 일이 흔하다 (`_save_side` 머리말). 주행 전이라 공짜다.
    for _ in range(3 if _rep_annot2 is not None else 1):
        _render_once()

if _cap or _rep_annot2 is not None:
    _sp = SHOT_STRIDE * int(os.environ.get("PIBT_SHOT_FPS", "30")) / 60.0
    print(f"[hl]   조립 시 {_sp:.1f}배속 · 렌더 호출이 1/{SHOT_STRIDE} 로 준다"
          + ("  (1번 꺼짐 — 2번만 찍는다)" if not _cap else ""))


# PIL 포맷 이름 — 확장자와 철자가 다르다 (jpg -> JPEG).
_PIL_FORMAT = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG"}.get(
    SHOT_EXT.lower(), SHOT_EXT.upper())


def _save_one(annot, out_dir, sim_t):
    """rgb 한 장을 live_pibt 와 **같은 파일명**으로 저장한다.

    ★ **원자적으로 쓴다** (2026-09-23). `.part` 로 쓰고 `os.replace` 로 옮긴다.

      검증 런은 **항상 SIGINT 로 끝난다** (`recorder.request_stop`). 그게
      `Image.save()` 한가운데를 끊으면 반쪽 PNG 가 남고, 조립이 그걸 만나

          [png] chunk too big
          Decoding error: Invalid data found when processing input
          frame= 219        <- 220장 중 219장

      으로 한 장을 버린다 (`side2` 실측). 영상은 나오지만 매 런 마지막
      프레임이 이렇게 빈다.

      `.part` 는 조립 glob(`f_*.png`)에 안 걸리므로, 끊겨서 남더라도
      무해하다 — 프레임이 **온전하거나 없거나** 둘 중 하나가 된다.
    """
    data = annot.get_data()
    if data is None or not len(data):
        raise RuntimeError("rgb 버퍼가 비었다")
    from PIL import Image
    final = os.path.join(out_dir, f"f_{int(round(sim_t * 100)):09d}.{SHOT_EXT}")
    tmp = final + ".part"
    # ★ 포맷을 **명시**한다. PIL 은 확장자로 포맷을 정하는데 `.part` 를 모른다
    #   — `ValueError: unknown file extension: .part` (r13peak 실측, 2026-09-23).
    Image.fromarray(data[:, :, :3]).save(tmp, format=_PIL_FORMAT)
    os.replace(tmp, final)


def _save_replicator(sim_t):
    """상단 한 장 (리플리케이터 경로). 측면은 `_save_side` 가 따로 한다."""
    global _shot_n, _shot_fail
    try:
        _save_one(_rep_annot, SHOTS, sim_t)
        _shot_n += 1
    except Exception as e:                                # noqa: BLE001
        _shot_fail += 1
        if _shot_fail <= 3:
            print(f"[hl] 캡처 실패 {_shot_fail}회: {e!r}")

# ===========================================================================
# ③ 주행 루프 — 우리가 민다
# ===========================================================================
#   Kit 의 `--exec` 경로에서는 앱 루프가 매 프레임 이것을 부른다(+렌더).
#   우리는 렌더만 뺀다. 순서는 같아야 한다 —
#       제어(_tick: pose 읽고 바퀴 명령) -> 적분(update_simulation)
#   콜백을 구독하지 않았으므로 _tick 이 두 번 불릴 일은 없다.
_physx = omni.physx.get_physx_interface()


def _step_physx(dt, t):
    _physx.update_simulation(dt, t)
    # 물리 결과를 USD 로 밀어 준다. probe 가 고른 pose 소스가 USD xform 이면
    # 이게 없으면 자세가 영영 안 변한다 (= 개루프로 잡힌다).
    try:
        _physx.update_transformations(False, True, False)
    except TypeError:                      # 시그니처가 버전마다 다르다
        try:
            _physx.update_transformations(updateToFastCache=False,
                                          updateToUsd=True,
                                          updateVelocitiesToUsd=False)
        except Exception:
            pass


_world = None
if STEPPER == "world":
    # 대안 경로. physx 직행이 안 될 때만 쓴다 — World 는 물리 씬 설정을
    # 건드릴 수 있어서 기본으로 두지 않는다.
    from isaacsim.core.api import World                 # noqa: E402
    _world = World(stage_units_in_meters=1.0, physics_dt=DT, rendering_dt=DT)
    print("[hl] stepper=world — World.step(render=False) 로 민다")


def _step(dt, t):
    if _world is not None:
        _world.step(render=False)
    else:
        _step_physx(dt, t)


t_sim = 0.0
n = 0
wall0 = time.time()
last_n, last_wall = 0, wall0
print(f"[hl] 주행 시작 — {len(fleet.drivers) if hasattr(fleet, 'drivers') else '?'}대")

try:
    while not state.get("done"):
        # 제어 (live_pibt 의 물리 콜백과 같은 함수다 — 통계·로그·중단판정 포함)
        on_physics(DT)
        if state.get("done"):
            break

        # 촬영 — **저장할 스텝에만** 그린다. 나머지 스텝은 렌더를 아예 안 부른다.
        #   viewport 경로: _tick 안에서 capture_viewport_to_file 이 이미 예약됐다.
        #     그것은 비동기라 **다음 렌더 프레임에 기록된다** — 여기 렌더가 그
        #     프레임이다. 이 호출이 없으면 예약만 쌓이고 파일은 안 생긴다.
        if (_cap or _rep_annot2 is not None) and state["n"] % SHOT_STRIDE == 0:
            # ★ 카메라를 **렌더 전에** 옮긴다 — 그래야 이 프레임에 반영된다.
            if _side_n_try % SIDE_EVERY == 0:
                _side_track(fleet)
            _render_once()
            # 상단 — 뷰포트면 live_pibt 가 자기 틱에서 찍는다 (여기서는 안 한다).
            if _cap == "replicator":
                _save_replicator(state["t"])
            # 측면 — **상단 경로와 무관하게** 같은 렌더 프레임에서 받는다.
            #   `PIBT_SIDE_EVERY` 로 주기를 늘리면 그만큼 복사가 준다.
            if _side_n_try % SIDE_EVERY == 0:
                _save_side(state["t"])
            _side_n_try += 1

        _step(DT, t_sim)
        t_sim += DT
        n += 1

        if n % REPORT == 0:
            wall = time.time() - wall0
            d_n, d_w = n - last_n, time.time() - last_wall
            last_n, last_wall = n, time.time()
            inst = (d_n * DT) / d_w if d_w > 0 else 0.0
            print(f"[hl] sim {t_sim:8.1f}s | 벽시계 {wall:8.1f}s | "
                  f"배속 {t_sim / wall if wall > 0 else 0:5.2f}x "
                  f"(순간 {inst:5.2f}x) | {d_w / d_n * 1000:6.2f} ms/step",
                  flush=True)

        if MAX_SIM and t_sim >= MAX_SIM:
            print(f"[hl] ★ 시뮬 상한 {MAX_SIM:.0f}s 도달 — 끊는다")
            state["done"] = True
            break
        if MAX_WALL and (time.time() - wall0) >= MAX_WALL:
            print(f"[hl] ★ 벽시계 상한 {MAX_WALL:.0f}s 도달 — 끊는다")
            state["done"] = True
            break
except KeyboardInterrupt:
    print("[hl] 중단 (Ctrl-C)")
    state["done"] = True
except Exception:
    import traceback
    print("[hl] ★ 루프 예외:")
    traceback.print_exc()
    state["done"] = True

# ===========================================================================
# 마무리 — 기록 저장은 _quit 이 한다 (멱등)
# ===========================================================================
wall = time.time() - wall0
print(f"[hl] 주행 종료 — sim {t_sim:.1f}s · 벽시계 {wall:.1f}s · "
      f"평균 배속 {t_sim / wall if wall > 0 else 0:.2f}x · 스텝 {n:,}")
try:
    print(f"[hl] {fleet.stats}")
except Exception as e:
    print(f"[hl] stats 출력 실패: {e!r}")

if _cap:
    # viewport 경로는 live_pibt 가 세므로(state) 그 값을, 리플리케이터는 우리 값을.
    _n = state.get("shots", 0) if _cap == "viewport" else _shot_n
    _f = state.get("shot_fail", 0) if _cap == "viewport" else _shot_fail
    _fps = int(os.environ.get("PIBT_SHOT_FPS", "30"))
    print(f"[hl] 촬영 {_n:,}장 · 실패 {_f}회 -> {SHOTS}")
    if _n:
        print(f"[hl]   영상 {_n / _fps:.0f}초 @{_fps}fps = "
              f"{SHOT_STRIDE * _fps / 60.0:.1f}배속")
        print(f"[hl]   조립: cd {SHOTS} && ffmpeg -framerate {_fps} "
              f"-pattern_type glob -i 'f_*.{SHOT_EXT}' "
              f"-c:v libx264 -pix_fmt yuv420p -crf 20 ../demo.mp4")
    else:
        print("[hl]   ★ 한 장도 안 나왔다 — 카메라 경로와 PIBT_SHOT_STRIDE 를 보라")

# ★ 2번영상 보고는 **`if _cap` 밖**이다 — 1번을 끈 판(`CAPTURE=side`)에서도
#   장수가 나와야 한다. 켠 적이 있으면 0 장이어도 찍는다: 백엔드는 `_side` 키가
#   없으면 **오류 없이** 버튼만 안 띄우므로, 조용한 0 장이 제일 나쁘다.
if SHOTS_SIDE and CAMERA_SIDE:
    _fps2 = int(os.environ.get("PIBT_SHOT_FPS", "30"))
    print(f"[hl] 촬영(2번영상) {_side_n:,}장 · 실패 {_side_fail}회 -> {SHOTS_SIDE}"
          + ("" if _side_n else f"   ★ 한 장도 안 나왔다 (카메라 {CAMERA_SIDE})"))
    if _side_n:
        print(f"[hl]   영상 {_side_n / _fps2:.0f}초 @{_fps2}fps = "
              f"{SHOT_STRIDE * SIDE_EVERY * _fps2 / 60.0:.1f}배속")
try:
    quit_fn(0)                             # 자세 기록 저장 (PIBT_RECORD 가 경로일 때)
except Exception as e:
    print(f"[hl] 마무리 예외: {e!r}")

simulation_app.close()
