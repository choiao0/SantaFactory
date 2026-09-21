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

★ 캡처(`PIBT_SHOTS`)는 뷰포트가 있어야 하므로 여기서는 못 쓴다. 영상이
  필요하면 `PIBT_RECORD=out/rec_pibt12.npz` 로 자세를 남기고 `runners/replay_wppl.py` 로 돌려라.
  그쪽이 원래 1:1 재생용이다.
"""
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_BASE = os.path.dirname(_HERE)

# ★ SimulationApp 보다 먼저 세운다 — live_pibt.py 가 임포트 시점에 읽는다.
os.environ["PIBT_HEADLESS"] = "1"
os.environ.setdefault("AMR_BASE", _BASE)
if os.environ.get("PIBT_SHOTS"):
    print("[hl] ★ PIBT_SHOTS 는 뷰포트가 필요하다 — 끄고 간다 "
          "(영상은 PIBT_RECORD=out/rec_pibt12.npz + replay_wppl.py)")
    os.environ["PIBT_SHOTS"] = ""

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

print(f"[hl] SimulationApp 기동 (headless) · dt={DT:.6f} · stepper={STEPPER}")
simulation_app = SimulationApp({"headless": True})

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
      f"여기서부터 **렌더 없음**")

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
try:
    quit_fn(0)                             # 자세 기록 저장 (PIBT_RECORD 가 경로일 때)
except Exception as e:
    print(f"[hl] 마무리 예외: {e!r}")

simulation_app.close()
