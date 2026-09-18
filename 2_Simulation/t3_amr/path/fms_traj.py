# -*- coding: utf-8 -*-
"""FMS 궤적을 **그대로 받는다** — `trajectories.json` → 우리 `history` (S15P21A106-240).

무엇이 밝혀졌길래
-----------------
우리 물리 판이 「FMS 이산을 물리로 증명한다」였는데, 층을 하나씩 열어 보니
여섯 중 셋이 우리 것이었다(격자·홈·헤딩). `PIBT_FMS_GRID` 로 그 셋을 맞췄지만,
그래도 **계획은 우리가 다시 한다.** 같은 입력이면 같은 답이 나와야 하지만,
「나와야 한다」와 「나온다」는 다르다.

그런데 그쪽에 **내보내기가 이미 있었다.**

    3_FMS/sim_engine/cli/export_isaac.py   SIM_EXPORT_ISAAC=1
        out/isaac_export_<tag>/trajectories.json
            robots   {rid: [[t_s, x, y] ...]}
            headings {rid: [[t_s, yaw] ...]}
            actions  {rid: [[t_s, act] ...]}   (move 가 아닌 틱만)

☹ 그리고 받는 쪽이 있었다 — `2_Simulation/isaac_replay.py`. **-219 에서 지웠다.**
  그 뒤로 우리는 계획을 스스로 해 왔다.

원본은 `kernel.export_log[rid] = [(틱, r, c, h, act) ...]` 이고 **우리 `history`
와 같은 것**이다. 내보낼 때만 미터·라디안으로 바뀌었을 뿐이라 역변환이 정확히
떨어진다.

    x = (c + 0.5)·CELL_M − OFFSET_M      ->  c = (x + OFFSET_M)/CELL_M − 0.5
    y = (r + 0.5)·CELL_M                 ->  r = y/CELL_M − 0.5
    yaw = atan2(dr, dc)                  ->  h  (네 값뿐이라 유일하다)
    t_s = 틱 × dt                        ->  틱 = round(t_s/dt)

★ 좌표 규약이 `PIBT_FMS_GRID` 의 `origin = (pitch/2 − OFFSET_M, pitch/2)` 와
  **같다.** 오늘 그걸 맞춰 뒀으므로 변환이 항등에 가깝다.

쓰는 법
-------
    from fms_traj import load_history
    history, meta = load_history(path)
    # 그다음은 우리 판과 완전히 같다
    actions = isaac_drive.extract_actions(history, geom)
    adg = isaac_drive.build_adg(chains)

자체 점검:
    source paths.sh
    python path/fms_traj.py <trajectories.json>
"""
import json
import math
import os
import sys

# DIRS 는 양쪽이 같은 것을 쓴다 — 여기서 다시 적으면 정의가 두 벌이 된다.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pibt_core_v2 as _pc                              # noqa: E402  (sim_engine 을 경로에)
from pibt_core import DIRS                              # noqa: E402

# 「yaw -> h」 표를 **DIRS 에서 굽는다.** 상수를 손으로 적으면 그쪽이 DIRS 를
# 바꿀 때 조용히 틀린다 (오늘만 여섯 번 본 실수다).
_YAW2H = {round(math.atan2(dr, dc), 4): h for h, (dr, dc) in enumerate(DIRS)}


def _cellof(x, y, cell_m, off_m):
    """미터 -> 칸. 내보내기가 소수 2자리로 반올림했지만 칸이 1 m 라 안전하다."""
    c = (x + off_m) / cell_m - 0.5
    r = y / cell_m - 0.5
    ri, ci = int(round(r)), int(round(c))
    if abs(r - ri) > 0.05 or abs(c - ci) > 0.05:
        raise ValueError(f"칸 중심에서 벗어난 점: ({x}, {y}) -> ({r:.3f}, {c:.3f})")
    return ri, ci


def _headof(yaw):
    h = _YAW2H.get(round(float(yaw), 4))
    if h is None:                                    # 반올림이 어긋나면 가장 가까운 것
        h = min(_YAW2H.items(), key=lambda kv: abs(kv[0] - float(yaw)))[1]
    return h


def load_history(path, cell_m=None, off_m=None, verbose=True):
    """`trajectories.json` -> (history, meta).

    `history[t][rid] = (r, c, h)` — `lifelong.run_lifelong` 이 내는 것과 같은 형식.

    ☹ 로그에 빈 틱이 있으면 **앞 값으로 채운다**. 내보내기는 틱마다 한 줄이지만,
      한 로봇의 로그가 먼저 끝나는 경우가 있다 — 그때 그 로봇을 빼 버리면
      `extract_actions` 가 사라진 로봇을 「이동」으로 읽는다.
    """
    import map_loader as ML
    cell_m = ML.CELL_M if cell_m is None else cell_m
    off_m = ML.OFFSET_M if off_m is None else off_m

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    dt = float(raw["dt_s"])
    robots, heads = raw["robots"], raw["headings"]
    if set(robots) != set(heads):
        raise ValueError("robots 와 headings 의 로봇 집합이 다르다")

    per = {}                                          # rid -> {틱: (r,c,h)}
    tmax = 0
    for k in sorted(robots, key=int):
        rid = int(k)
        hh = {round(float(t) / dt): yaw for t, yaw in heads[k]}
        per[rid] = {}
        for t_s, x, y in robots[k]:
            t = int(round(float(t_s) / dt))
            r, c = _cellof(float(x), float(y), cell_m, off_m)
            per[rid][t] = (r, c, _headof(hh.get(t, 0.0)))
            tmax = max(tmax, t)

    history, filled = [], 0
    last = {}
    for t in range(tmax + 1):
        st = {}
        for rid, log in per.items():
            s = log.get(t)
            if s is None:
                s = last.get(rid)
                if s is None:
                    continue                          # 아직 등장 전
                filled += 1
            st[rid] = s
            last[rid] = s
        history.append(st)

    meta = dict(dt=dt, model=raw.get("model"), n_robots=len(per),
                ticks=len(history), filled=filled,
                tasks=len(raw.get("tasks") or []),
                cell_m=cell_m, off_m=off_m)
    if verbose:
        print(f"[fms_traj] {os.path.basename(path)} · 모델 {meta['model']} · dt {dt}s")
        print(f"[fms_traj]   로봇 {meta['n_robots']}대 · 틱 {meta['ticks']:,} "
              f"(= {meta['ticks'] * dt:,.0f}s) · 태스크 {meta['tasks']:,}")
        if filled:
            print(f"[fms_traj]   ☹ 빈 틱을 앞 값으로 채움 {filled:,}칸")
    return history, meta


def _main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    history, meta = load_history(sys.argv[1])

    # ── 형식이 우리 파이프라인에 맞는가 ────────────────────────────────────
    import isaac_drive as D
    import pibt_scene as PS
    geom = PS.make_geom(meta["cell_m"])
    bad = []
    for t in range(len(history) - 1):
        for a, s0 in history[t].items():
            s1 = history[t + 1].get(a)
            if s1 is None:
                continue
            dr, dc = s1[0] - s0[0], s1[1] - s0[1]
            if s0[2] != s1[2]:                        # 회전
                if (dr, dc) != (0, 0):
                    bad.append((t, a, "회전인데 칸이 움직였다", s0, s1))
                elif (s1[2] - s0[2]) % 4 not in (1, 3):
                    bad.append((t, a, "90도가 아니다", s0, s1))
            elif (dr, dc) != (0, 0):                  # 이동
                f, b = DIRS[s0[2]], DIRS[(s0[2] + 2) % 4]
                if (dr, dc) not in (f, b):
                    bad.append((t, a, "전진도 후진도 아니다", s0, s1))
    print(f"\n── 전이 검사 ── {'★ 전부 합법' if not bad else f'☹ 위반 {len(bad):,}건'}")
    for row in bad[:5]:
        print(f"   t={row[0]} agent{row[1]}  {row[2]}  {row[3]} -> {row[4]}")

    chains, order, stats = D.extract_actions(history, geom)
    n = sum(len(ch) for ch in chains)
    kinds = {}
    for ch in chains:
        for act in ch:
            kinds[getattr(act, "kind", "?")] = kinds.get(getattr(act, "kind", "?"), 0) + 1
    print(f"\n── extract_actions ── 체인 {len(chains)}개 · 동작 **{n:,}개**")
    print(f"   종류 {dict(sorted(kinds.items(), key=lambda kv: -kv[1]))}")

    adg = D.build_adg(chains)
    cyc = adg.topological_order() is None
    print(f"\n── build_adg ── {'☹☹ **순환**' if cyc else '★ 비순환'}")
    print("   -> 비순환이면 우리 실행층에 **그대로** 먹일 수 있다")
    return 1 if (bad or cyc) else 0


if __name__ == "__main__":
    sys.exit(_main())
