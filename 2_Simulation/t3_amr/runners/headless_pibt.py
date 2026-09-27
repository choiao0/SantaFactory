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
#   백엔드가 상단 키에서 `_fpv` 를 계산해 MinIO 에 있는지 확인하고 버튼을
#   띄운다. 그래서 **파일 이름만** 지키면 되고 결과 페이로드는 안 바뀐다.
#
#   ☹ 부하 — 리플리케이터 경로는 **저장할 스텝에만** 렌더한다(1/STRIDE).
#     시점이 둘이면 그 스텝에서 render product 가 둘이라 렌더가 대략 2배,
#     디스크·조립·업로드도 2배다. 다만 물리는 그대로다 — 매 스텝 도는 물리에
#     비하면 3 Hz 렌더의 2배는 작다. **실측 전이다.**
SHOTS_FPV = (os.environ.get("PIBT_SHOTS_FPV", "") or "").strip()
CAMERA_FPV = (os.environ.get("PIBT_CAMERA_FPV", "") or "").strip()
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

# ===========================================================================
# 물리 지표 (-275) — 워밍업 뒤 창만 센다. 엣지가 PIBT_PHYSICS_OUT 을 읽어 결과에 싣는다
# ===========================================================================
#   구간 재생이면 `state["slice"]` 에 워밍업·창이 있다(live_pibt 가 궤적에서 읽었다).
#   구간이 아니면 워밍업 0 · 창 = 지금까지 전부로 센다.
PHYSICS_OUT = (os.environ.get("PIBT_PHYSICS_OUT", "") or "").strip()
_SLICE = state.get("slice") or {}
WARMUP = float(_SLICE.get("warmup_s") or 0.0)
WINDOW = float(_SLICE.get("window_s") or 0.0)
sys.path.insert(0, os.path.join(os.environ.get("W", os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "path"))
import physics_report as PR                             # noqa: E402

#   DES 궤적을 재생한 런(live_pibt 가 traj_dt 를 채웠다)만 계획과 견준다. 자체 계획이면 None —
#   지연·창 수행은 null 로 나간다(`physics_report.summarize` 주석).
_PLANNED = ([fleet.rt.release_time(a) for a in fleet.rt.adg.actions
             if getattr(a, "release_tick", None) is not None]
            if state.get("traj_dt") is not None else None)
_PH_BASE = None                                         # 워밍업 끝 기준선


def _physics(t_sim, wall):
    return PR.summarize(fleet.stats, _PH_BASE, sim_s=t_sim, wall_s=wall,
                        warmup_s=WARMUP, window_s=WINDOW or max(t_sim - WARMUP, 0.0),
                        n_robots=len(fleet.drivers), planned_s=_PLANNED, rt=fleet.rt,
                        des_window=_SLICE.get("des_window"))


def _physics_write(t_sim, wall):
    if not PHYSICS_OUT:
        return None
    try:
        doc = _physics(t_sim, wall)
        PR.write_atomic(PHYSICS_OUT, doc)
        return doc
    except Exception as e:                  # 지표 때문에 주행을 멈추지 않는다 — 알리기만
        print(f"[hl] ☹ 물리 지표 쓰기 실패: {e!r}", flush=True)
        return None


if _SLICE:
    print(f"[hl] ★★ 구간 재생 — 워밍업 {WARMUP:g}s 뒤 창 {WINDOW:g}s 를 센다 · "
          f"계획 동작 {len(_PLANNED or ()):,}개 · 지표 -> {PHYSICS_OUT or '(안 씀)'}")
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
_fpv_n = 0                 # 측면 장수 — 상단과 따로 센다 (경로가 다르다)
_fpv_fail = 0              # 측면 저장 실패 누적 (상단처럼 몇 번은 참는다)
_fpv_n_try = 0             # 측면 캡처 시도 횟수 — PIBT_FPV_EVERY 주기 계산용


def _attach_fpv():
    """측면 카메라를 **리플리케이터로** 붙인다. 실패하면 None.

    ★ 상단 경로와 **무관하게** 돈다 (2026-09-23).
      상단이 뷰포트면 `live_pibt` 의 `capture_viewport_to_file` 이 찍고, 상단이
      리플리케이터면 `_rep_annot` 이 찍는다. 측면은 어느 쪽이든 자기 render
      product 를 갖는다 — 뷰포트는 하나뿐이라 카메라를 바꿔 끼울 수 없고,
      바꿔 끼우면 캡처가 비동기라(`live_pibt.py:497`) 엉뚱한 프레임이 찍힌다.

    ☹ 2026-09-22 에 이 함수가 **리플리케이터 분기 안에만** 있었다. 그런데 이
      서버는 뷰포트 분기로 돌아서 측면이 한 장도 안 나왔다 (`hl264c`: 상단
      6,861장 · 측면 0장). 오류도 경고도 없었다 — 백엔드가 `_fpv` 키를
      못 찾아 버튼만 안 생긴다.

    부하 — 실측 1.0 ms/step 이하 (촬영 ON 16.58 vs OFF 15.60, STRIDE 20).
    """
    if not (SHOTS_FPV and CAMERA_FPV):
        return None
    try:
        import omni.kit.app as _ka
        _ka.get_app().get_extension_manager() \
           .set_extension_enabled_immediate("omni.replicator.core", True)
        import omni.replicator.core as rep                # noqa: E402
        os.makedirs(SHOTS_FPV, exist_ok=True)
        _w, _h = (int(x) for x in FPV_RES.split("x"))
        annot = rep.AnnotatorRegistry.get_annotator("rgb")
        annot.attach([rep.create.render_product(CAMERA_FPV, (_w, _h))])
        print(f"[hl] 촬영 ON (2번영상) {SHOTS_FPV} · 카메라 {CAMERA_FPV} · {_w}x{_h}"
              + (" · 고정" if FPV_FOLLOW < 0 else
                 f" · 로봇 {'auto' if FPV_AUTO else FPV_FOLLOW} "
                 + (f"3인칭 {FPV_DIST:g}m" if FPV_VIEW == "chase"
                    else f"드론 뒤 {FPV_BACK:g}m · 높이 {FPV_UP:g}m" if FPV_VIEW == "drone"
                    else f"**1인칭** 앞 {FPV_FWD:g}m · 높이 {FPV_EYE_Z:g}m"
                       f" · 초점 {FPV_FOCAL:g}mm"))
              + (f" · {FPV_EVERY}번에 한 번" if FPV_EVERY > 1 else ""))
        return annot
    except Exception as e:                                # noqa: BLE001
        print(f"[hl] ☹ 2번영상을 못 켠다 — 1번만 찍는다: {e!r}")
        return None


FPV_FAIL_MAX = int(os.environ.get("PIBT_FPV_FAIL_MAX", "") or 20)

# ★★ 측면은 **AMR 한 대를 대각선 뒤에서** 잡는다 (2026-09-23).
#
#   처음엔 `Cam_Overview`(창고 전체 조망)를 썼는데 요청은 「한 대의 대각 측면」
#   이었다. 조망으로는 1.5 m 짜리 AMR 이 점이라 선반의 상자가 안 보인다.
#
#   고정 카메라(`Cam_Spot`)로는 **로봇이 그 자리를 지날 때만** 잡힌다 — 빈
#   통로가 찍힌 영상이 백엔드로 올라갈 수 있다. 그래서 매 캡처마다 카메라를
#   대상 로봇 뒤로 옮긴다.
#
#       PIBT_FPV_FOLLOW   auto(기본) | 로봇 번호 | -1(카메라 고정)
#       PIBT_FPV_VIEW     fpv(기본) | chase | drone (뒤 PIBT_FPV_BACK · 높이 PIBT_FPV_UP)
#       PIBT_FPV_DIST     chase 일 때 거리 [m]
#       PIBT_FPV_LR       chase 일 때 좌/우  (-1 왼쪽 · +1 오른쪽)
#
#   ★ 기본은 **1인칭**이다 (2026-09-23). 3인칭 추종(chase)은 카메라가 창고를
#     넓게 담아 렌더가 무겁다. 1인칭은 통로 앞만 보므로 화면에 드는 기하가
#     훨씬 적다. 주행 방향이 그대로 보여 시연에도 읽기 쉽다.
#
#     ☹ 복사 비용은 **안 줄어든다** — 텍스처를 호스트로 옮기는 몫은 픽셀 수에만
#       달렸다. 줄이려면 `PIBT_FPV_RES` 를 내리거나 `PIBT_FPV_EVERY` 를 올린다.
# ★ 기본은 **auto** — 초반에 가장 많이 움직인 로봇을 고른다 (2026-09-23).
#   0번은 충전존에서 시작해 한참 서 있는 일이 잦아 영상이 심심했다. 어느 번호가
#   바쁜지는 시드·궤적마다 달라서 손으로 고르면 매번 빗나간다.
#       PIBT_FPV_FOLLOW=auto  (기본)  ·  =5 특정 로봇  ·  =-1 카메라 고정
_sf = (os.environ.get("PIBT_FPV_FOLLOW", "") or "auto").strip().lower()
FPV_AUTO = (_sf == "auto")
FPV_FOLLOW = 0 if FPV_AUTO else (int(_sf) if _sf.lstrip("-").isdigit() else 0)
# 이만큼 캡처한 뒤 고른다. STRIDE 40 이면 15회 = 물리 600스텝 = 시뮬 10초.
FPV_AUTO_AFTER = max(1, int(os.environ.get("PIBT_FPV_AUTO_AFTER", "") or 15))
# 고르기 전 구간을 영상에서 버릴지 (기본 켬). 끄면 정지 화면으로 시작한다.
WARMSTART = (os.environ.get("PIBT_FPV_WARMSTART", "") or "1") not in ("0", "", "no", "off")
FPV_VIEW = (os.environ.get("PIBT_FPV_VIEW", "") or "fpv").strip().lower()
FPV_DIST = float(os.environ.get("PIBT_FPV_DIST", "") or 6.0)
FPV_LR = 1.0 if (os.environ.get("PIBT_FPV_LR", "") or "-1").strip() != "-1" else -1.0
# drone 일 때 — 로봇 뒤로 [m] · 높이 [m] · 겨냥점을 구동축 앞으로 [m]. 20 mm 와 짝으로 차체 전체(뒤 1.11 m ·
#   높이 1.65 m)가 화면 아래 1/3 에 들고 앞 통로·포장대가 위에 든다.
FPV_BACK = float(os.environ.get("PIBT_FPV_BACK", "") or 4.5)
FPV_UP = float(os.environ.get("PIBT_FPV_UP", "") or 5.0)
FPV_AHEAD = float(os.environ.get("PIBT_FPV_AHEAD", "") or 1.0)
# drone 카메라 방향을 이만큼씩만 로봇 방향으로 돌린다(캡처마다) — 제자리 회전 때 5배속 영상이 휙 돌지 않게.
FPV_YAW_EASE = min(1.0, max(0.05, float(os.environ.get("PIBT_FPV_YAW_EASE", "") or 0.35)))
# ★ 1인칭 눈 위치 — **차 앞면보다 앞**이어야 한다.
#   구동축이 앞이라(heading_offset=0) 차체는 뒤로 뻗지만, 선반은 축 앞으로도
#   0.39 m 나오고 z 0.22~1.65 를 채운다. 축 바로 위에 두면 카메라가 **선반
#   구조물 안**에 들어가 포스트와 데크만 보인다.
#   축에서 앞으로 0.55 m · 높이 1.20 m 가 기본 — 차 앞머리에 단 대시캠 자리다.
FPV_FWD = float(os.environ.get("PIBT_FPV_FWD", "") or 0.55)
FPV_EYE_Z = float(os.environ.get("PIBT_FPV_EYE_Z", "") or 1.20)
# 겨냥점을 앞으로 이만큼, 바닥 쪽으로 내려 본다 — 통로와 앞차가 같이 들어온다.
FPV_LOOK = float(os.environ.get("PIBT_FPV_LOOK", "") or 12.0)
FPV_LOOK_Z = float(os.environ.get("PIBT_FPV_LOOK_Z", "") or 0.60)
# 측면을 **몇 번에 한 번** 찍나. 1 이면 상단과 같은 주기.
#   렉이 심하면 이것을 올린다 — 비용이 그만큼 나뉜다. 대신 측면 영상이 그 배수만큼
#   빨라진다 (상단 10배속 · EVERY=3 이면 측면 30배속).
FPV_EVERY = max(1, int(os.environ.get("PIBT_FPV_EVERY", "") or 1))
# 근접 화면이라 조망만큼 클 필요가 없다. **복사량이 곧 비용**이다 —
# 리플리케이터는 텍스처를 호스트로 직접 복사하고(Kit 이 그렇게 경고한다),
# 1280x720 두 시점이 28 ms/step(배속 0.60)이었다.
FPV_RES = (os.environ.get("PIBT_FPV_RES", "") or "960x540").lower()
_fpv_cam_warned = False
_fpv_xop = None            # 카메라 transform op — 한 번만 만들고 값만 갱신한다
# ★ 초점거리 [mm]. 씬의 `Cam_Spot` 은 **24 mm 광각**으로 만들어져 있다
#   (`build_amr_scene_v2.py:308`). 눈높이 1.2 m 에서 화각 47도면 아래쪽이 4 m 앞
#   바닥을 잡아 **하단 절반이 바닥**이 된다. 주행 화면으로는 35 mm 쯤이 낫다.
#     24 mm -> 화각 47.0도    35 mm -> 33.5도    50 mm -> 23.7도
FPV_FOCAL = float(os.environ.get("PIBT_FPV_FOCAL", "") or (20.0 if FPV_VIEW == "drone" else 35.0))
_fpv_cam_n = 0             # 카메라를 옮긴 횟수 (로그용)
_fpv_yaw = None            # drone 카메라가 지금 보는 방향 (FPV_YAW_EASE 로 로봇 방향을 따라간다)
_fpv_pick = None           # auto 로 고른 로봇 (한 번 고르면 안 바꾼다)
_fpv_home = None           # 각 로봇의 시작 자리 — 움직인 거리를 재는 기준

# ★★ 영상 글씨 (-244) — 「이 AMR 이 지금 무슨 주문을 어디서 어디로 나르나」.
#   영상만 봐서는 AMR 이 주문을 처리하는지 그냥 돌아다니는지 모른다. DES 구간(궤적 파일)에서 로봇별
#   운행(픽업 → 적재 → 운반 → 하역)을 짜서(`path/demo_overlay.py`) 프레임에 적는다. 구간 재생에서만.
#     · 1인칭 — 윗줄(로봇 · 창 시계) · 운행(주문·토트 · 출발 → 도착) · 단계 알약 · 그 로봇 실적
#     · 천장 — 로봇마다 단계 색 원 · 진행 방향 · 번호, 1인칭 대상은 분홍 고리, 포장대 이름, 범례, 전체 실적.
#       120 m 광각에서 AMR 이 흰 점 18 px 라 바닥과 구분이 안 됐다. USD 에 표시 prim 을 달면 물리 링크
#       밑이라 판이 달라질 위험이 있어 **프레임 위에 그린다** (물리 무관).
#       PIBT_FPV_HUD=0         1인칭 글씨 끈다
#       PIBT_TOP_MARK=0        천장 표시 끈다
#       PIBT_TOP_FIT=0         천장 카메라를 로봇이 다닌 범위에 맞추지 않는다 (씬 기본 120 m 전경)
#       PIBT_HUD_FONT=<ttf>    한글 글꼴 (이미지에 fonts-noto-cjk). 없으면 영어 글씨 + PIL 기본 글꼴
#   ★ auto 추종은 **창 안에서 운행을 가장 많이 끝내는 로봇**을 첫 프레임부터 따라간다. 초반 10초를
#     지켜보고 고르는 방식(`FPV_AUTO_AFTER`)은 구간표가 없을 때만 쓴다.
HUD_ON = (os.environ.get("PIBT_FPV_HUD", "") or "1") not in ("0", "no", "off")
TOP_MARK = (os.environ.get("PIBT_TOP_MARK", "") or "1") not in ("0", "no", "off")
TOP_FIT = (os.environ.get("PIBT_TOP_FIT", "") or "1") not in ("0", "no", "off")
# 글꼴 — Noto Sans CJK KR(이미지 fonts-noto-cjk, 굵기 셋을 쓴다), 없으면 나눔고딕 (-279)
_HUD_FONTS = ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
              "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf")
HUD_FONT = (os.environ.get("PIBT_HUD_FONT", "")
            or next((f for f in _HUD_FONTS if os.path.isfile(f)), _HUD_FONTS[0])).strip()
# 「통행 대기」 — 따라가는 로봇이 이동 단계인데 이만큼 서 있으면 붙인다 (앞 로봇이 지나가길 기다리는 중)
WAIT_AFTER_S = 3.0
WAIT_MOVE_M = 0.10
_follow_ref = None         # (x, y, 마지막으로 움직인 시뮬 초)
# 구동축은 차 앞쪽이다 — 차체는 뒤로 1.11 m · 앞으로 0.39 m (iw.hub). 천장 원은 차체 가운데에 둔다.
BODY_BACK_M = 0.36
# 포장대 이름은 그 칸(로봇이 서는 자리)이 아니라 벽 쪽으로 이만큼 내려 적는다 — 선 로봇을 안 가린다.
STATION_LABEL_DY_M = 1.6
_hud_warned, _top_warned = False, False


def _hud_load():
    """구간 재생이면 (운행표, 따라갈 로봇). 아니거나 실패하면 (None, None) — 글씨 없이 찍는다."""
    want = (HUD_ON and SHOTS_FPV and CAMERA_FPV) or (TOP_MARK and SHOTS)
    if not (_SLICE and want):
        return None, None
    try:
        import demo_overlay as DO
        path = (os.environ.get("PIBT_TRAJ", "") or "").strip()
        if not os.path.isabs(path):
            path = os.path.join(os.environ.get("W", _BASE), path)
        lang = "ko" if os.path.isfile(HUD_FONT) else "en"
        tl = DO.Timeline.from_file(path, lang)
        rid = tl.busiest()
        pick = int(rid) if rid is not None and str(rid).isdigit() and int(rid) in fleet.drivers else None
        print(f"[hl] 영상 글씨 ON — 운행 {sum(len(v) for v in tl.trips.values())}개 · 글꼴 "
              + (HUD_FONT if lang == "ko" else "(없음 → 영어)")
              + (f" · 창에서 가장 바쁜 로봇 {pick}" if pick is not None else ""), flush=True)
        return tl, pick
    except Exception as e:                                # noqa: BLE001
        print(f"[hl] ☹ 영상 글씨를 못 켠다 — 글씨 없이 찍는다: {e!r}", flush=True)
        return None, None


_tl, _hud_pick = _hud_load()
_hud_ok = _tl is not None and HUD_ON and bool(SHOTS_FPV and CAMERA_FPV)
_top = None                 # (카메라→월드, 초점, 수평 조리개, 크기, 포장대 화면 좌표) — `_top_setup`


def _plan_k(a):
    """로봇 a 의 계획 틱 — 그 로봇이 Isaac 에서 실제로 붙잡고 있는 동작 기준 (`demo_overlay.plan_tick`)."""
    import demo_overlay as DO
    act = fleet.rt.pending(fleet.slot[a])
    return DO.plan_tick(act.tick if act is not None else None, fleet.rt.clock, fleet.rt.tick_s)


def _window_clock(sim_t):
    return min(sim_t - WARMUP, WINDOW) if sim_t >= WARMUP else None


def _hud_prep(sim_t):
    """1인칭 프레임에 얹을 글씨를 정해 **그리는 함수**를 돌려준다(그리기·저장은 쓰기 스레드가 한다).
    단계는 **그 로봇이 Isaac 에서 실제로 붙잡고 있는 동작**으로 정한다 — DES 시각으로 고르면 물리가 늦은 만큼
    화면과 글씨가 어긋난다. 실패하면 한 번만 알리고 끈다 — 프레임은 잃지 않는다."""
    global _hud_ok, _hud_warned, _follow_ref
    try:
        import math as _m
        import demo_overlay as DO
        who = _fpv_pick if _fpv_pick is not None else FPV_FOLLOW
        k, rid = _plan_k(who), str(who)
        # 멈춰 있는데 「운반 중」이면 고장 난 것처럼 보인다 — 서 있는 시간을 재서 「통행 대기」를 붙인다 (-279)
        px, py, _ = fleet.drivers[who].axle_pose()
        if _follow_ref is None or _m.hypot(px - _follow_ref[0], py - _follow_ref[1]) > WAIT_MOVE_M:
            _follow_ref = (px, py, sim_t)
        waiting = sim_t - _follow_ref[2] >= WAIT_AFTER_S
        lines, key = _tl.lines(rid, k, _window_clock(sim_t), waiting=waiting), _tl.phase(rid, k).key
        return lambda img: DO.draw(img, lines, HUD_FONT, key)
    except Exception as e:                                # noqa: BLE001
        if not _hud_warned:
            _hud_warned = True
            print(f"[hl] ☹ 1인칭 글씨 준비 실패 — 끄고 글씨 없이 찍는다: {e!r}", flush=True)
        _hud_ok = False
        return None


def _top_setup(cam_path, size):
    """천장 카메라를 로봇이 다닌 범위에 맞추고(`PIBT_TOP_FIT`), 투영에 쓸 값을 돌려준다. 실패하면 None."""
    if _tl is None or not TOP_MARK:
        return None
    try:
        import numpy as _np
        import demo_overlay as DO
        from pxr import Gf, Usd, UsdGeom                 # noqa: E402
        import omni.usd                                  # noqa: E402
        prim = omni.usd.get_context().get_stage().GetPrimAtPath(cam_path)
        cam = UsdGeom.Camera(prim)
        focal = float(cam.GetFocalLengthAttr().Get())
        hap = float(cam.GetHorizontalApertureAttr().Get())
        xf = UsdGeom.Xformable(prim)
        if TOP_FIT and _tl.extent:
            m = DO.top_down(*DO.fit_top(_tl.extent, size, focal, hap))
            ops = xf.GetOrderedXformOps()
            op = ops[0] if len(ops) == 1 and ops[0].GetOpType() == UsdGeom.XformOp.TypeTransform else None
            if op is None:
                xf.ClearXformOpOrder()
                op = xf.AddTransformOp()
            op.Set(Gf.Matrix4d(*[v for row in m for v in row]))
        m = _np.array(xf.ComputeLocalToWorldTransform(Usd.TimeCode.Default()))
        st = [(name, *uv) for name, uv in zip(_tl.stations, DO.project(
            [(x, y - STATION_LABEL_DY_M, 0.0) for x, y in _tl.stations.values()], m, focal, hap, size))
              if uv is not None]
        print(f"[hl] 천장 표시 ON — 카메라 {cam_path} · 높이 {m[3][2]:.0f} m · 중심 ({m[3][0]:.1f}, "
              f"{m[3][1]:.1f})" + (" (로봇이 다닌 범위에 맞춤)" if TOP_FIT else "") + f" · 포장대 {len(st)}곳",
              flush=True)
        return m, focal, hap, size, st
    except Exception as e:                                # noqa: BLE001
        print(f"[hl] ☹ 천장 표시를 못 켠다 — 표시 없이 찍는다: {e!r}", flush=True)
        return None


def _top_prep(sim_t):
    """천장 프레임에 얹을 로봇 표시를 정해 **그리는 함수**를 돌려준다. 자세·단계는 여기(주 스레드)서 읽는다.
    실패하면 한 번만 알리고 끈다 — 프레임은 잃지 않는다."""
    global _top, _top_warned
    try:
        import math as _m
        import demo_overlay as DO
        m, focal, hap, size, st = _top
        agents = list(fleet.agents)
        pts, ks = [], {}
        for a in agents:
            x, y, yaw = fleet.drivers[a].axle_pose()
            fx, fy = _m.cos(yaw), _m.sin(yaw)
            cx, cy = x - BODY_BACK_M * fx, y - BODY_BACK_M * fy
            pts += [(cx, cy, 1.0), (cx + 0.75 * fx, cy + 0.75 * fy, 1.0)]
            ks[str(a)] = _plan_k(a)
        uv = DO.project(pts, m, focal, hap, size)
        marks = []
        for i, a in enumerate(agents):
            c, n = uv[2 * i], uv[2 * i + 1]
            if c is None or n is None:
                continue
            marks.append(DO.Mark(num=int(a) + 1, u=c[0], v=c[1], hu=n[0] - c[0], hv=n[1] - c[1],
                                 key=_tl.phase(str(a), ks[str(a)]).key,
                                 follow=bool(SHOTS_FPV) and a == _fpv_pick))
        lines, lang = _tl.top_lines(ks, _window_clock(sim_t), len(agents)), _tl.lang
        return lambda img: DO.draw_top(img, marks, lines, HUD_FONT, st, lang)
    except Exception as e:                                # noqa: BLE001
        if not _top_warned:
            _top_warned = True
            print(f"[hl] ☹ 천장 표시 준비 실패 — 끄고 표시 없이 찍는다: {e!r}", flush=True)
        _top = None
        return None


FPV_BACK_MIN = 1.2         # drone 카메라를 벽 앞으로 당길 때의 최소 뒤 거리 [m]
_fpv_back = None


def _drone_back(x, y, dx, dy):
    """drone 카메라의 뒤 거리 — 카메라 자리가 벽·선반 칸이면 로봇 쪽으로 당긴다 (-279).

    로봇이 벽 가까이에서 돌면 4.5 m 뒤 카메라가 벽 안에 묻혀 화면이 하얗게 찼다. 로봇에서 뒤로 0.25 m 씩
    지도(`state["free"]`)를 짚어 가다 처음 막힌 칸 앞에서 멈춘다. 당길 때는 바로, 물러날 때는 천천히 — 튀지 않게.
    """
    global _fpv_back
    want = FPV_BACK
    free, g = state.get("free"), getattr(fleet, "g", None)
    if free is not None and g is not None:
        d = 0.25
        while d <= FPV_BACK + 1e-9:
            r, c = g.world_to_cell(x - d * dx, y - d * dy)
            if not (0 <= r < free.shape[0] and 0 <= c < free.shape[1]) or not free[r, c]:
                want = max(FPV_BACK_MIN, d - 0.35)
                break
            d += 0.25
    if _fpv_back is None or want < _fpv_back:
        _fpv_back = want
    else:
        _fpv_back += 0.15 * (want - _fpv_back)
    return _fpv_back


def _fpv_track(fleet_):
    """측면 카메라를 대상 로봇에 붙인다 — 기본은 **1인칭 주행 시점**.

    실패해도 주행을 죽이지 않는다 — 한 번만 알리고 그 뒤로 조용히 넘어간다.
    카메라가 안 움직이면 마지막 자리에 머물 뿐이다.
    """
    global _fpv_cam_warned, _fpv_pick, _fpv_home, _fpv_xop, _fpv_cam_n, _fpv_yaw
    if (not FPV_AUTO and FPV_FOLLOW < 0) or _rep_annot2 is None or not CAMERA_FPV:
        return
    try:
        import math as _m
        # ★ auto — 초반에 **가장 많이 움직인** 로봇을 골라 그 뒤로 고정한다.
        #   고르는 동안은 FPV_FOLLOW(기본 0)를 따라간다. 한 번만 갈아탄다 —
        #   매 프레임 갈아타면 화면이 튄다.
        who = FPV_FOLLOW
        if FPV_AUTO:
            if _fpv_pick is None and _hud_pick is not None:
                _fpv_pick = _hud_pick
                print(f"[hl]   [cam] ★ 로봇 {_fpv_pick} 를 따라간다 (DES 구간표 — 창 안 운행이 "
                      f"가장 많다) — 첫 프레임부터 녹화한다", flush=True)
            if _fpv_pick is not None:
                who = _fpv_pick
            else:
                n_rb = len(fleet_.drivers)
                poses = [fleet_.drivers[i].axle_pose() for i in range(n_rb)]
                if _fpv_home is None:
                    _fpv_home = [(p[0], p[1]) for p in poses]
                if _fpv_cam_n >= FPV_AUTO_AFTER:
                    moved = [_m.hypot(p[0] - h[0], p[1] - h[1])
                             for p, h in zip(poses, _fpv_home)]
                    _fpv_pick = max(range(n_rb), key=lambda i: moved[i])
                    who = _fpv_pick
                    print(f"[hl]   [cam] ★ 로봇 {_fpv_pick} 를 따라간다 "
                          f"(시뮬 초반에 {moved[_fpv_pick]:.1f} m 이동 · "
                          f"가만히 있던 대수 {sum(1 for d in moved if d < 0.2)})"
                          + ("  — 여기서부터 녹화한다" if WARMSTART else ""),
                          flush=True)
        drv = fleet_.drivers[who]
        x, y, yaw = drv.axle_pose()
        from pxr import Gf, UsdGeom                      # noqa: E402
        import omni.usd                                  # noqa: E402
        fx, fy = _m.cos(yaw), _m.sin(yaw)
        if FPV_VIEW == "chase":
            # 3인칭 — 뒤로 0.75d, 옆으로 0.5d, 높이 0.55d
            d = FPV_DIST
            eye = Gf.Vec3d(x - 0.75*d*fx - 0.5*d*(-fy)*FPV_LR,
                           y - 0.75*d*fy - 0.5*d*(fx)*FPV_LR, 0.55*d)
            tgt = Gf.Vec3d(x, y, 0.75)
        elif FPV_VIEW == "drone":
            # ★ 드론 추종 (-244) — 로봇 **바로 뒤·선반 위**에서 로봇과 그 앞을 내려다본다. 옆으로 비끼지 않아
            #   통로에서 선반에 안 가리고, 1인칭처럼 포장대 앞 흰 벽만 찍히지도 않는다 — 로봇 선반의 상자와
            #   포장대의 토트가 한 화면에 든다. 방향은 FPV_YAW_EASE 로 천천히 따라간다.
            if _fpv_yaw is None:
                _fpv_yaw = yaw
            _fpv_yaw += FPV_YAW_EASE * _m.atan2(_m.sin(yaw - _fpv_yaw), _m.cos(yaw - _fpv_yaw))
            cfx, cfy = _m.cos(_fpv_yaw), _m.sin(_fpv_yaw)
            back = _drone_back(x, y, cfx, cfy)
            eye = Gf.Vec3d(x - back*cfx, y - back*cfy, FPV_UP)
            tgt = Gf.Vec3d(x + FPV_AHEAD*cfx, y + FPV_AHEAD*cfy, 0.3)
        else:
            # ★ 1인칭 — 차 앞머리에서 주행 방향을 본다 (대시캠).
            eye = Gf.Vec3d(x + FPV_FWD*fx, y + FPV_FWD*fy, FPV_EYE_Z)
            tgt = Gf.Vec3d(x + (FPV_FWD + FPV_LOOK)*fx,
                           y + (FPV_FWD + FPV_LOOK)*fy, FPV_LOOK_Z)
        f = (tgt - eye).GetNormalized()
        r = Gf.Cross(f, Gf.Vec3d(0, 0, 1)).GetNormalized()
        u = Gf.Cross(r, f)
        # ★ transform op 은 **한 번만 만들고 값만 갱신**한다 (2026-09-23).
        #   매 프레임 `ClearXformOpOrder()` + `AddTransformOp()` 를 하면 이미
        #   있는 `xformOp:transform` 을 다시 만들려다 두 번째부터 조용히 실패할
        #   수 있다. 그러면 카메라가 **첫 자리에 그대로 멈춘다** — 영상이 한
        #   장면에서 안 바뀐다.
        if _fpv_xop is None:
            prim = omni.usd.get_context().get_stage().GetPrimAtPath(CAMERA_FPV)
            if not prim or not prim.IsValid():
                raise RuntimeError(f"카메라 prim 이 없다: {CAMERA_FPV}")
            # 초점거리도 여기서 한 번 잡는다 — 씬 기본(24 mm)은 주행 화면에 너무 넓다.
            try:
                UsdGeom.Camera(prim).GetFocalLengthAttr().Set(FPV_FOCAL)
            except Exception as _fe:                     # noqa: BLE001
                print(f"[hl]   [cam] 초점거리를 못 바꿨다 (씬 기본 그대로): {_fe!r}")
            xf = UsdGeom.Xformable(prim)
            xf.ClearXformOpOrder()
            _fpv_xop = xf.AddTransformOp()
        _fpv_xop.Set(Gf.Matrix4d(
            r[0], r[1], r[2], 0, u[0], u[1], u[2], 0,
            -f[0], -f[1], -f[2], 0, eye[0], eye[1], eye[2], 1))
        # 움직이는지 로그로 보이게 한다 — 안 움직이면 여기 좌표가 그대로다.
        if _fpv_cam_n < 3 or _fpv_cam_n % 100 == 0:
            print(f"[hl]   [cam] #{_fpv_cam_n} 로봇{who} ({x:.2f}, {y:.2f}, "
                  f"{_m.degrees(yaw):.0f}deg) -> 눈 ({eye[0]:.2f}, {eye[1]:.2f}, "
                  f"{eye[2]:.2f})", flush=True)
        _fpv_cam_n += 1
    except Exception as e:                               # noqa: BLE001
        if not _fpv_cam_warned:
            _fpv_cam_warned = True
            print(f"[hl] ☹ 1인칭 카메라 추종 실패 — 고정 화각으로 간다: {e!r}")


def _save_fpv(sim_t):
    """측면 한 장. 실패가 `FPV_FAIL_MAX` 회 쌓이면 **측면만** 끈다.

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
    global _rep_annot2, _fpv_n, _fpv_fail
    if _rep_annot2 is None:
        return
    # ★ auto 로 로봇을 **고르기 전까지는 저장하지 않는다** (2026-09-23).
    #
    #   고르려면 시뮬 초반을 지켜봐야 하는데, 그동안은 `FPV_FOLLOW`(기본 0)를
    #   따라간다. 0번은 충전존에서 시작해 서 있으므로 **영상이 정지 화면으로
    #   시작**했다. 그 구간을 통째로 버리면 첫 프레임부터 움직인다.
    #
    #   버리는 길이는 `PIBT_FPV_AUTO_AFTER x SHOT_STRIDE` 물리스텝이다
    #   (STRIDE 40 · 15회면 시뮬 10초). `PIBT_FPV_WARMSTART=0` 으로 끌 수 있다.
    if FPV_AUTO and WARMSTART and _fpv_pick is None:
        return
    try:
        _save_one(_rep_annot2, SHOTS_FPV, sim_t, _hud_prep if _hud_ok else None, "fpv")
        _fpv_n += 1
    except Exception as e:                                # noqa: BLE001
        _fpv_fail += 1
        if _fpv_fail <= 3:
            print(f"[hl] 2번영상 저장 실패 {_fpv_fail}회 (계속 시도): {e!r}")
        if _fpv_fail >= FPV_FAIL_MAX:
            print(f"[hl] ☹ 2번영상 저장이 {FPV_FAIL_MAX}회 실패 — 2번영상을 끈다. "
                  f"마지막: {e!r}")
            if _fpv_n == 0:
                print("[hl]   ★ 한 장도 못 받았다 = 지연이 아니라 구조 문제다. "
                      "뷰포트가 있는 판에서는 리플리케이터 대신 **두 번째 "
                      "뷰포트**(create_viewport_window + capture_viewport_to_file, "
                      "상단이 쓰는 그 API)로 가야 한다.")
            _rep_annot2 = None

if SHOTS:
    os.makedirs(SHOTS, exist_ok=True)
    # ★ 천장 표시(-244)는 프레임을 **우리 손으로 저장해야** 그 위에 그릴 수 있다. 뷰포트 캡처
    #   (`live_pibt._shot`)는 비동기로 파일을 바로 써서 틈이 없다. 표시를 켜면 뷰포트 캡처를 끄고
    #   (`state["vp"] = None` — live_pibt 가 더는 안 찍는다) 같은 카메라를 리플리케이터로 받는다.
    #   뷰포트 자체 렌더도 멈춘다 — 안 쓰는 화면을 그리느라 렌더가 두 번 돌지 않게.
    #   ☹ 뷰포트 렌더를 못 멈추면 **바꾸지 않는다** — 둘 다 돌면 렌더가 두 번이다. 천장은 표시 없이 뷰포트로 찍는다.
    if state.get("vp") is not None and _tl is not None and TOP_MARK:
        try:
            state["vp"].updates_enabled = False
            state["vp"] = None
            print("[hl] 천장 표시를 그리려고 뷰포트 캡처 대신 리플리케이터로 찍는다")
        except Exception as e:                            # noqa: BLE001
            print(f"[hl] ☹ 뷰포트 렌더를 못 멈췄다 — 천장은 표시 없이 뷰포트로 찍는다: {e!r}")
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
            _top = _top_setup(_cam, (_w, _h))       # 렌더 프로덕트 전에 — 첫 장부터 맞춘 화각
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
#   (`CAPTURE=fpv`)이 있어서, `if SHOTS:` 블록 **밖**에서 붙인다.
#   1번 프레임이 13대 10분 판에 14 GB 라 시연 영상만 뽑을 때는 그게 아깝다.
if SHOTS_FPV and CAMERA_FPV:
    _rep_annot2 = _attach_fpv()
    # ★ 붙인 직후 몇 프레임을 **버린다.** annotator 는 첫 렌더에 버퍼가
    #   안 차는 일이 흔하다 (`_save_fpv` 머리말). 주행 전이라 공짜다.
    for _ in range(3 if _rep_annot2 is not None else 1):
        _render_once()

if _cap or _rep_annot2 is not None:
    _sp = SHOT_STRIDE * int(os.environ.get("PIBT_SHOT_FPS", "30")) / 60.0
    print(f"[hl]   조립 시 {_sp:.1f}배속 · 렌더 호출이 1/{SHOT_STRIDE} 로 준다"
          + ("  (1번 꺼짐 — 2번만 찍는다)" if not _cap else ""))


# PIL 포맷 이름 — 확장자와 철자가 다르다 (jpg -> JPEG).
_PIL_FORMAT = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG"}.get(
    SHOT_EXT.lower(), SHOT_EXT.upper())


# ★ 프레임 쓰기는 **뒤 스레드**가 한다 (-244). PNG 인코딩(zlib)이 1280x720 한 장에 193 ms(레벨 6)라,
#   천장 영상을 리플리케이터로 받자 주 루프가 40 ms/step(배속 0.42)까지 느려졌다 — 뷰포트 캡처는 Kit 이
#   네이티브 스레드에서 쓰므로 몰랐던 비용이다. 레벨 1(41 ms, 파일 +10~18 %)로 낮추고 글씨 그리기·인코딩·
#   쓰기를 스레드 둘에 맡긴다(zlib 은 GIL 을 놓는다). 주 루프는 버퍼 복사와 그릴 값 계산만 한다.
#       PIBT_PNG_LEVEL   PNG 압축 0~9 (기본 1)
import threading                                        # noqa: E402
from concurrent.futures import ThreadPoolExecutor      # noqa: E402

PNG_LEVEL = int(os.environ.get("PIBT_PNG_LEVEL", "") or 1)
_IO_MAX = 8                 # 밀린 쓰기 상한 — 넘으면 가장 오래된 것을 기다린다(메모리 상한 ~30 MB)
_io = ThreadPoolExecutor(max_workers=2, thread_name_prefix="shot")
_io_pending = []
# 쓰기 스레드가 센다 — 영상별 **쓰기** 실패(그 프레임이 없다)와 글씨 실패(프레임은 글씨 없이 있다). 끝 보고가
#   제출 수에서 쓰기 실패를 뺀다 — 안 그러면 디스크가 차도 「실패 0회」로 찍힌다.
_io_lock = threading.Lock()
_io_fail = {"top": 0, "fpv": 0}
_paint_fail = 0


def _io_count(stream):
    """실패 하나를 센다(잠금). 처음 셋만 알리도록 지금까지의 합을 돌려준다."""
    global _paint_fail
    with _io_lock:
        if stream == "paint":
            _paint_fail += 1
        else:
            _io_fail[stream] += 1
        return _paint_fail + sum(_io_fail.values())


def _write_frame(arr, final, paint, stream):
    """쓰기 스레드 — 글씨를 얹고(`paint`) `.part` 로 쓴 뒤 `os.replace`. 실패는 세고 처음 셋만 알린다."""
    try:
        from PIL import Image
        img = Image.fromarray(arr)
        if paint is not None:
            try:
                img = paint(img)
            except Exception as e:                        # noqa: BLE001 — 글씨가 안 돼도 프레임은 쓴다
                if _io_count("paint") <= 3:
                    print(f"[hl] ☹ 글씨 그리기 실패 (프레임은 글씨 없이 쓴다): {e!r}", flush=True)
        tmp = final + ".part"
        # ★ 포맷을 **명시**한다. PIL 은 확장자로 포맷을 정하는데 `.part` 를 모른다
        #   — `ValueError: unknown file extension: .part` (r13peak 실측, 2026-09-23).
        img.save(tmp, format=_PIL_FORMAT, **({"compress_level": PNG_LEVEL} if _PIL_FORMAT == "PNG" else {}))
        os.replace(tmp, final)
    except Exception as e:                                # noqa: BLE001
        if _io_count(stream) <= 3:
            print(f"[hl] ☹ 프레임 쓰기 실패: {final}: {e!r}", flush=True)


def _io_drain():
    """밀린 쓰기를 다 끝낸다 — 끝낼 때(SIGINT 포함) 조립 전에 부른다."""
    _io.shutdown(wait=True)
    if _paint_fail or any(_io_fail.values()):
        print(f"[hl] ☹ 프레임 쓰기 실패 천장 {_io_fail['top']} · 추종 {_io_fail['fpv']}회 · "
              f"글씨 실패 {_paint_fail}회", flush=True)


def _save_one(annot, out_dir, sim_t, overlay=None, stream="top"):
    """rgb 한 장을 live_pibt 와 **같은 파일명**으로 저장한다. `overlay(sim_t)` 가 그리는 함수를 주면 얹는다.

    버퍼는 다음 렌더에 덮이므로 **복사해서** 쓰기 스레드(`_write_frame`)에 넘긴다.

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
    import numpy as np
    data = annot.get_data()
    if data is None or not len(data):
        raise RuntimeError("rgb 버퍼가 비었다")
    final = os.path.join(out_dir, f"f_{int(round(sim_t * 100)):09d}.{SHOT_EXT}")
    arr = np.array(data[:, :, :3], copy=True)
    paint = overlay(sim_t) if overlay is not None else None
    _io_pending[:] = [f for f in _io_pending if not f.done()]
    while len(_io_pending) >= _IO_MAX:
        _io_pending.pop(0).result()
    _io_pending.append(_io.submit(_write_frame, arr, final, paint, stream))


def _save_replicator(sim_t):
    """상단 한 장 (리플리케이터 경로). 측면은 `_save_fpv` 가 따로 한다."""
    global _shot_n, _shot_fail
    try:
        _save_one(_rep_annot, SHOTS, sim_t, _top_prep if _top is not None else None)
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
            if _fpv_n_try % FPV_EVERY == 0:
                _fpv_track(fleet)
            _render_once()
            # 상단 — 뷰포트면 live_pibt 가 자기 틱에서 찍는다 (여기서는 안 한다).
            if _cap == "replicator":
                _save_replicator(state["t"])
            # 측면 — **상단 경로와 무관하게** 같은 렌더 프레임에서 받는다.
            #   `PIBT_FPV_EVERY` 로 주기를 늘리면 그만큼 복사가 준다.
            if _fpv_n_try % FPV_EVERY == 0:
                _save_fpv(state["t"])
            _fpv_n_try += 1

        _step(DT, t_sim)
        t_sim += DT
        n += 1

        if _PH_BASE is None and WARMUP and t_sim >= WARMUP:
            _PH_BASE = PR.snapshot(fleet.stats, fleet.rt)
            print(f"[hl] ★ 워밍업 {WARMUP:g}s 끝 — 여기서부터 창 {WINDOW:g}s 를 센다", flush=True)

        if n % REPORT == 0:
            wall = time.time() - wall0
            d_n, d_w = n - last_n, time.time() - last_wall
            last_n, last_wall = n, time.time()
            inst = (d_n * DT) / d_w if d_w > 0 else 0.0
            # ☹ 앞머리 `[hl] sim <초>s` 는 엣지가 정규식으로 읽는다(edge/recorder.py) — 바꾸지 말 것.
            #   창 시각(워밍업을 뺀 것)은 뒤에 따로 붙인다.
            print(f"[hl] sim {t_sim:8.1f}s | 벽시계 {wall:8.1f}s | "
                  f"배속 {t_sim / wall if wall > 0 else 0:5.2f}x "
                  f"(순간 {inst:5.2f}x) | {d_w / d_n * 1000:6.2f} ms/step"
                  + (f" | 창 {max(0.0, t_sim - WARMUP):7.1f}s" if _SLICE else ""),
                  flush=True)
            _physics_write(t_sim, wall)

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
_io_drain()                                            # 밀린 프레임 쓰기를 끝낸다 — 조립 전에
try:
    print(f"[hl] {fleet.stats}")
except Exception as e:
    print(f"[hl] stats 출력 실패: {e!r}")
# ★ 마지막 지표 — 검증 런은 늘 SIGINT(Stop)로 여기 온다. 엣지는 업로드 전에 이 파일을 읽는다.
_ph = _physics_write(t_sim, wall)
if _ph:
    _lag, _wa = _ph["lag"], _ph["window_actions"]
    print(f"[hl] 물리 지표 — 창 {_ph['window_sim_s']:.0f}s · 접촉 로봇 {_ph['robot_contacts']} "
          f"랙 {_ph['rack_contacts']} · 최소 간격 {_ph['robot_min_gap_m']} m · "
          f"지연 p50 {_lag['p50_s']} p90 {_lag['p90_s']} 최대 {_lag['max_s']} s · "
          f"창 동작 {_wa['started']}/{_wa['planned']} (밀림 {_wa['overdue_s']} s) -> {PHYSICS_OUT}",
          flush=True)

if _cap:
    # viewport 경로는 live_pibt 가 세므로(state) 그 값을, 리플리케이터는 우리 값을.
    _n = state.get("shots", 0) if _cap == "viewport" else _shot_n - _io_fail["top"]
    _f = state.get("shot_fail", 0) if _cap == "viewport" else _shot_fail + _io_fail["top"]
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

# ★ 2번영상 보고는 **`if _cap` 밖**이다 — 1번을 끈 판(`CAPTURE=fpv`)에서도
#   장수가 나와야 한다. 켠 적이 있으면 0 장이어도 찍는다: 백엔드는 `_fpv` 키가
#   없으면 **오류 없이** 버튼만 안 띄우므로, 조용한 0 장이 제일 나쁘다.
if SHOTS_FPV and CAMERA_FPV:
    _fpv_n, _fpv_fail = _fpv_n - _io_fail["fpv"], _fpv_fail + _io_fail["fpv"]
    _fps2 = int(os.environ.get("PIBT_SHOT_FPS", "30"))
    print(f"[hl] 촬영(2번영상) {_fpv_n:,}장 · 실패 {_fpv_fail}회 -> {SHOTS_FPV}"
          + ("" if _fpv_n else f"   ★ 한 장도 안 나왔다 (카메라 {CAMERA_FPV})"))
    if _fpv_n:
        print(f"[hl]   영상 {_fpv_n / _fps2:.0f}초 @{_fps2}fps = "
              f"{SHOT_STRIDE * FPV_EVERY * _fps2 / 60.0:.1f}배속")
try:
    quit_fn(0)                             # 자세 기록 저장 (PIBT_RECORD 가 경로일 때)
except Exception as e:
    print(f"[hl] 마무리 예외: {e!r}")

simulation_app.close()
