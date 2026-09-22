# -*- coding: utf-8 -*-
"""계획 층 정합성 — 우리 `lifelong` 을 FMS 와 **같은 입력**으로 돌려 맞댄다.

    MAP=$MAP python tools/plan_parity.py          # 3h (38,880틱) · 약 3분
    HZ=2520 python tools/plan_parity.py           # 짧게

Isaac 불필요. 입력은 FMS 꾸러미(`docs/_정합성_s104/`)를 그대로 쓴다.

무엇을 맞대고 무엇을 안 맞대나
------------------------------
**궤적(틱별 좌표)은 안 맞댄다.** 격자·회전 비용이 설계상 다르다
(`lifelong.py` 머리말 [FMS 와 다른 것]). **태스크 수준**이 맞는 층위다.

주문은 `packing_assign_s104.csv`(FMS **출력**)를 쓴다. `JsonOrderStream` 은
포장대를 난수로 다시 뽑아 수열이 달라지므로 **정합성 대조에 못 쓴다**
(`fms_stream.py` 의 JsonOrderStream 주석).

☹ 남는 차이는 **설계상**이다 — 우리에게 대치 상태기계(FMS `standoffs`)와
  스윙 예약(`PIBT_SWING_HARD` 기본 꺼짐)이 없다. 둘 다 「기다림」이라 없으면
  처리량이 낙관적으로 나온다. 2026-09-22 기준 완료 +6.2 % 다.

이 파일이 찾아낸 것 (2026-09-22)
--------------------------------
    복귀존이 19칸 넓었다      c=102 한 열. `_cell_of` 반올림 + 끝 포함
                              -> 상류 `ML.load_charge_zone` 을 부르게 고쳤다
                              -> 존 대기 379 -> 864 (FMS 815)
"""
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
W = os.environ.get("TW", os.path.join(HERE, ".."))
os.environ["W"] = W
os.environ.setdefault("PIBT_FMS_GRID", "1")
os.environ.setdefault("PIBT_CAPACITY", "6")
os.environ.setdefault("PIBT_SVC_PER_TOTE", "18")
os.environ.setdefault("PIBT_TURN_SWEEP", "1")
sys.path.insert(0, os.path.join(W, "path"))

N, PITCH, SEED = 13, 1.0, 104
HORIZON = int(os.environ.get("HZ", "38880"))
# 꾸러미 위치 — `docs/` 는 .gitignore 라 워크트리에는 없다. 다른 체크아웃의
#   것을 쓰려면 `PARITY_BUNDLE` 로 준다.
B = os.environ.get("PARITY_BUNDLE") or os.path.join(W, "docs", "_정합성_s104")
if not os.path.isdir(B):
    sys.exit("★ FMS 꾸러미가 없습니다: %s\n"
             "  `docs/` 는 .gitignore 라 저장소에 없다 — 꾸러미를 받아 두어야 한다." % B)

import pibt_scene as PS                                       # noqa: E402
from fms_stream import FileOrderStream                        # noqa: E402
from lifelong import run_lifelong                             # noqa: E402

t0 = time.perf_counter()
geom, free, starts, goals = PS.setup_lifelong(os.environ["MAP"], N, PITCH, SEED,
                                              verbose=False)
zone = PS.charge_zone_cells(free, geom)
print("[parity] 씬 %.1fs · 격자 %s · 존 %d칸"
      % (time.perf_counter() - t0, free.shape, len(zone)))

stream = FileOrderStream(os.path.join(B, "packing_assign_s104.csv"),
                         geom, free, os.environ["MAP"], HORIZON, verbose=False)
t0 = time.perf_counter()
history, cells_hist, info = run_lifelong(
    free, starts, goals, horizon=HORIZON, seed=SEED, shifts="out",
    zone_cells=zone, stream=stream, verbose=False)
print("[parity] 계획 %.1fs (%d틱 · %d대)" % (time.perf_counter() - t0, HORIZON, N))

fms = json.load(io.open(os.path.join(B, "summary_r13.json"), encoding="utf-8"))

# ★ 회전 마스크 비율은 **상류 함수가 낸다.** 직접 계산하면 값이 갈린다 —
#   초판이 `_APPLIED / (free.size*4)` 로 2.77 을 냈다 (맞는 값은 3.54 %).
import map_loader as ML                                       # noqa: E402
import pibt.geometry as _geo                                  # noqa: E402
_mask = ML.turn_mask(PS._fms_map_dir(), ML.ROBOT_DIMS, _geo.FOOTPRINT_MARGIN_M)
ratio = ML.masked_turn_ratio(free, _mask)

# FMS 존 칸 — 이것도 상류 함수로.
_zm = ML.load_charge_zone(free, PS._fms_map_dir())
fms_zone = int((_zm & free).sum()) if _zm is not None else None

bad = 0
def row(label, f, o, tol=None):
    global bad
    if f is None or o is None:
        m = "?"
    elif tol is None:
        m = "✓" if str(f) == str(o) else "☹"
    else:
        try:
            m = "✓" if abs(float(f) - float(o)) <= tol * max(1.0, abs(float(f))) else "☹"
        except Exception:
            m = "?"
    if m == "☹":
        bad += 1
    print("  %-22s %14s %14s   %s" % (label, f, o, m))

print("\n" + "=" * 62)
print("  %-22s %14s %14s" % ("항목", "FMS", "우리"))
print("=" * 62)
print("  ── 입력 (여기가 틀리면 나머지는 볼 필요 없다) ──")
row("회전 마스크 비율", fms["turn_masked"], round(ratio, 4), tol=0.02)
row("격자 통행 칸", 8640, int(free.sum()))
row("복귀존 칸", fms_zone, len(zone))
row("로봇 수", fms["n_robots"], N)
row("horizon 틱", fms["horizon_steps"], HORIZON)
row("hd_after", 16, info.get("hd_after"))
row("만든 태스크(토트)", fms["totes"], info.get("tasks_spawned"))
print("  ── 결과 ──")
row("완료 태스크", fms["orders_done"], info.get("tasks_done"), tol=0.05)
row("정체 로봇·틱", fms["stag_robot_ticks"], info.get("stag_robot_ticks"), tol=0.20)
row("존 대기 스텝", fms["zone_wait_steps"], info.get("zone_wait_steps"), tol=0.20)
row("존 재선택", fms["zone_retargets"], info.get("zone_retargets"))
row("존 저하", fms["zone_degraded"], info.get("zone_degraded"))
row("존 점유 평균", fms["zone_occ_mean"], info.get("zone_occ_mean"), tol=0.20)
row("idle 이동", fms["idle_moves"], info.get("zone_idle_moves"))
print("=" * 62)
print("  불일치 %d" % bad)
print("\n  ☹ 완료 태스크 차이는 **설계상**이다 — 대치 상태기계(FMS standoffs %d ·"
      % fms.get("standoffs", 0))
print("     ticks %d)와 스윙 예약이 우리에게 없다. 기다림이 빠지면 낙관적이 된다."
      % fms.get("standoff_ticks", 0))
