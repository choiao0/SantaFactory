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

씬 빌더용 계획 폴더를 궤적 첫 틱으로 만들기 (-275, `run_record.sh` 가 궤적 재생에서 부른다):
    python path/fms_traj.py --plan-folder <trajectories.json> <plan/traj_pibt_h/fleet_NN>
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


def _read_traj(path):
    """파일을 읽고 **로봇 집합이 맞는지**만 본다."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if set(raw["robots"]) != set(raw["headings"]):
        raise ValueError("robots 와 headings 의 로봇 집합이 다르다")
    return raw


#: ★★ **구간 파일** (S15P21A106-275). DES 6시간 중 피크 10분만 잘라 물리로 본다.
#
#   내보내기 형식에 `slice` 블록 하나가 더 붙는다. 시각(`t_s`)은 **DES 원래 시각
#   그대로**이고, 여기서 `t_start_s` 를 빼 틱 0 부터 다시 센다 — 틱 0 이 곧 스폰이다.
#
#       slice.t_start_s   구간 시작 = t0 − 워밍업. 모든 로봇이 이 시각에 한 줄씩 있다
#       slice.t0_s        검증 창 시작 (피크 10분의 첫 초)
#       slice.warmup_s    t0 전에 미리 굴리는 시간 — 지표에서 뺀다
#       slice.window_s    검증 창 길이 (실제 시간 초 = 시뮬 초)
#       slice.speed_mps   DES 가 쓴 순항 속도 — 실행 속도를 여기에 맞춘다
#
#   ☹ 워밍업을 두는 이유 — FMS 는 여러 틱짜리 동작을 **첫 틱에** 끝난 자리로
#     적는다. t0 에 딱 잘라 스폰하면 움직이던 로봇이 최대 3.3 s 앞선 자리에 멈춘
#     채로 선다. 워밍업 동안 계획대로 굴려 두면 t0 에는 이미 제 속도로 달리고 있다.
SLICE_KEYS = ("t_start_s", "t0_s", "warmup_s", "window_s")


def _slice_block(raw):
    """구간 파일이면 `slice` 블록, 아니면 None. 필수 키가 빠졌으면 바로 멈춘다."""
    s = raw.get("slice")
    if s is None:
        return None
    missing = [k for k in SLICE_KEYS if s.get(k) is None]
    if missing:
        raise ValueError(f"slice 블록에 {missing} 가 없다")
    t_start, t0, warm = float(s["t_start_s"]), float(s["t0_s"]), float(s["warmup_s"])
    if abs((t0 - t_start) - warm) > 1e-6 * max(1.0, t0):
        raise ValueError(f"slice: t0_s − t_start_s ({t0 - t_start:g}) != warmup_s ({warm:g})")
    return s


def _states_by_robot(raw, dt, cell_m, off_m, t_start_s=0.0):
    """`{rid: {틱: (r,c,h)}}` 와 마지막 틱. 좌표·헤딩 변환이 여기 한 곳에만 있다.

    `t_start_s` 를 빼고 센다 — 구간 파일이면 구간 시작이 틱 0 이다. 그 앞 줄은 버린다.
    """
    per, tmax = {}, 0
    k0 = round(float(t_start_s) / dt)
    for k in sorted(raw["robots"], key=int):
        rid = int(k)
        hh = {round(float(t) / dt) - k0: yaw for t, yaw in raw["headings"][k]}
        per[rid] = {}
        for t_s, x, y in raw["robots"][k]:
            t = int(round(float(t_s) / dt)) - k0
            if t < 0:
                continue
            r, c = _cellof(float(x), float(y), cell_m, off_m)
            per[rid][t] = (r, c, _headof(hh.get(t, 0.0)))
            tmax = max(tmax, t)
    return per, tmax


def _fill_gaps(per, tmax):
    """빈 틱을 **앞 값으로** 채워 `history` 를 만든다. (history, 채운 칸 수)

    ☹ 한 로봇의 로그가 먼저 끝나는 경우가 있다. 그때 그 로봇을 빼 버리면
      `extract_actions` 가 **사라진 로봇을 「이동」으로 읽는다.**
    """
    history, filled, last = [], 0, {}
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
    return history, filled


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

    raw = _read_traj(path)
    dt = float(raw["dt_s"])
    sl = _slice_block(raw)
    per, tmax = _states_by_robot(raw, dt, cell_m, off_m,
                                 t_start_s=float(sl["t_start_s"]) if sl else 0.0)
    if sl:
        late = [rid for rid, log in per.items() if 0 not in log]
        if late:
            raise ValueError(f"slice: 로봇 {late[:5]} 가 구간 시작(틱 0)에 없다 — "
                             "스폰 자리를 모른다")
    history, filled = _fill_gaps(per, tmax)

    meta = dict(dt=dt, model=raw.get("model"), n_robots=len(per),
                ticks=len(history), filled=filled,
                tasks=len(raw.get("tasks") or []),
                cell_m=cell_m, off_m=off_m, slice=dict(sl) if sl else None)
    if verbose:
        print(f"[fms_traj] {os.path.basename(path)} · 모델 {meta['model']} · dt {dt}s")
        print(f"[fms_traj]   로봇 {meta['n_robots']}대 · 틱 {meta['ticks']:,} "
              f"(= {meta['ticks'] * dt:,.0f}s) · 태스크 {meta['tasks']:,}")
        if sl:
            print(f"[fms_traj]   ★★ 구간 — DES {float(sl['t_start_s']):,.0f}s 부터 "
                  f"(워밍업 {float(sl['warmup_s']):g}s + 창 {float(sl['window_s']):g}s, "
                  f"t0 = {float(sl['t0_s']):,.0f}s)")
        if filled:
            print(f"[fms_traj]   ☹ 빈 틱을 앞 값으로 채움 {filled:,}칸")
    return history, meta


#: ★★ 궤적의 **시간표**를 지킨다 (-240, 2026-09-18).
#
#   ☹ 칸 열이 같아도 **간격이 다르면 다른 주행**이다. 이산에서 10틱 떨어져
#     지나간 두 대가 자유 주행에서는 바로 뒤에 붙어 간다. 칸은 안 겹쳐도
#     몸은 41.3 mm 안으로 들어온다 — **접촉을 정하는 것이 바로 그 간격**이다.
#
#     그 상태로 접촉이 나면 「그쪽 계획 탓」이라고 말할 수 없다. 우리가 간격을
#     안 지켜서일 수 있다. 그러면 이 판을 돌리는 의미가 없어진다.
#
#   그래서 **동작마다** `release_tick` 을 제 계획 틱으로 박는다. 실행은 그
#   시각보다 **일찍은 못 가고 늦게는 갈 수 있다** — 물리가 느린 만큼 밀린다.
#   FMS 시계가 바닥이 되고, 그 위에서 물리가 얼마나 밀리는지가 측정된다.
#
#       PIBT_TRAJ_SCHEDULE=0   순서만 지킨다 (☹ 간격이 안 지켜진다)
#       (기본)                 **시간표를 지킨다**
#
#   ☹ 우리 lifelong 판은 `release_tick` 을 **태스크 첫 동작에만** 건다(-211).
#     로봇이 일찍 끝내도 계획 시각까지 서 있는 것이 막힘의 66.2 % 였기 때문이다.
#     여기서는 그 66.2 % 가 **버그가 아니라 재현하려는 대상**이라 전부 건다.
TRAJ_SCHEDULE = os.environ.get("PIBT_TRAJ_SCHEDULE", "1") not in ("0", "", "no", "off")


def _stamp_schedule(chains, meta, verbose):
    """★★ 시간표를 지킨다 — 동작마다 **제 계획 틱**을 릴리스 바닥으로 박는다.

    끄면(`PIBT_TRAJ_SCHEDULE=0`) 순서만 지키고 간격은 안 지킨다.
    """
    if not TRAJ_SCHEDULE:
        if verbose:
            print("[fms_traj]   ☹ PIBT_TRAJ_SCHEDULE=0 — **순서만** 지킨다."
                  " 두 로봇 사이 간격이 이산과 달라진다")
        return 0
    n = 0
    for ch in chains:
        for act in ch:
            act.release_tick = act.tick
            n += 1
    meta["scheduled"] = n
    if verbose:
        print(f"[fms_traj]   ★★ 시간표 적용 — 동작 {n:,}개에 릴리스 바닥을 박았다"
              f" (일찍은 못 가고 늦게는 간다)")
    return n


def _cycle_nodes(adg):
    """위상정렬로 **안 빠지는 노드**들 — 고리에 갇힌 것. 없으면 빈 리스트."""
    indeg = {a.uid: len(adg.preds[a.uid]) for a in adg.actions}
    q = [u for u, d in indeg.items() if d == 0]
    seen = set()
    while q:
        u = q.pop()
        seen.add(u)
        for v in adg.succs[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    return [a.uid for a in adg.actions if a.uid not in seen]


def build(path, geom, verbose=True):
    """`trajectories.json` -> `(adg, order, history, info)`.

    `isaac_drive.plan_and_build_lifelong` 과 **같은 것**을 돌려준다. 다른 점은
    계획을 **안 한다**는 것뿐이다 — 그쪽이 낸 동작 열을 그대로 세운다.

    ☹ ADG 발자국은 **계획 발자국과 같아야 한다** (2026-09-18 실측).
      같은 궤적(`--footprint=exact,front_2cell`)을 세워 보면

          규칙 끔    순환
          앞 2칸     **비순환**   <- 계획과 같은 발자국
          앞 4칸     **순환**     <- 우리가 채택한 규칙

      계획기가 안 지킨 칸을 ADG 가 예약하면 없던 의존이 생기고 고리가 된다.
      4칸은 회전마다 `mA·mB` 를 더 잡는데 그쪽 계획기는 그걸 안 봤다.
      -> 이 궤적을 먹일 때는 **`PIBT_FRONT_RULE=2`** 로 맞춰야 한다.

    ☹ `sweep_audit` 은 없다 — `cells_hist`(계획기가 실제로 예약한 칸)가 궤적에
      안 담겨 있다. 겹침 감시는 주행 중 `FleetController` 가 실제 자세로 한다.
    """
    import isaac_drive as D
    history, meta = load_history(path, verbose=verbose)
    chains, order, stats = D.extract_actions(history, geom)

    _stamp_schedule(chains, meta, verbose)

    adg = D.build_adg(chains)
    if adg.topological_order() is None:
        raise RuntimeError(
            "ADG 에 순환이 있다 — 실행하면 데드락이다.\n"
            "   ★ 계획 발자국과 맞는지 보라. `--footprint=exact,front_2cell` 로 만든\n"
            "     궤적은 **PIBT_FRONT_RULE=2** 여야 비순환이다 (4칸은 순환).")

    import metrics
    horizon = len(history) - 1
    cp = metrics.critical_path(adg, geom)
    info = {
        "actions": stats,
        "lifelong": {"tasks_done": meta["tasks"], "fms_traj": meta},
        "throughput": metrics.throughput(meta["tasks"], horizon, geom, makespan=cp),
        "dispatch": "fms-traj",
    }
    return adg, order, history, info


def find_cycle(adg, limit=3):
    """의존 고리를 **실제로** 뽑는다 — 「순환이다」만으로는 원인을 못 고른다.

    위상정렬로 남는 노드(진입차수가 0 이 안 되는 것)에서 DFS 로 되돌아오는
    간선을 찾는다. `topological_order()` 와 같은 자료(`preds`/`succs`)를 쓴다.
    """
    left = _cycle_nodes(adg)                         # 고리에 갇힌 것들
    if not left:
        return []
    inside = set(left)
    out, color, stack = [], {}, []

    def dfs(u):
        color[u] = 1
        stack.append(u)
        for v in adg.succs[u]:
            if v not in inside:
                continue
            if color.get(v, 0) == 1:                 # 되돌아오는 간선 = 고리
                out.append(stack[stack.index(v):] + [v])
                if len(out) >= limit:
                    return True
            elif color.get(v, 0) == 0 and dfs(v):
                return True
        stack.pop()
        color[u] = 2
        return False

    sys.setrecursionlimit(max(10000, len(left) + 1000))
    for u in left:
        if color.get(u, 0) == 0 and dfs(u):
            break
    return out


def write_plan_folder(path, fleet_dir, verbose=True):
    """궤적 **첫 틱**으로 씬 빌더용 계획 폴더를 만든다 (-275). 만든 대수를 돌려준다.

    씬 빌더(`amr/main.py run` → `build_amr_scene_v2.py --traj --starts`)는 대수별 계획
    폴더의 `trajectories.json`·`starts.json` 을 읽어 로봇을 세운다. 궤적 재생은 계획을
    안 하므로 그 폴더가 없다 — 로컬에서는 손으로 둔 `plan/` 이 있었지만 컨테이너에는 없다.

    스폰 좌표는 러너와 **같은 기하**로 낸다 — `pibt_scene.setup_lifelong` 이 `PIBT_FMS_GRID`
    를 보고 FMS 격자 원점을 쓴다. 따로 계산하면 원점이 어긋나 live_pibt 가 「스폰이 궤적
    첫 틱과 다르다」로 다시 세운다.
    """
    import pibt_scene as PS
    history, meta = load_history(path, verbose=False)
    n = meta["n_robots"]
    pitch = float(os.environ.get("PIBT_PITCH", "") or 1.0)
    seed = int(os.environ.get("PIBT_SEED", "") or 104)
    geom, _free, _st, _goals = PS.setup_lifelong(os.environ["MAP"], n, pitch, seed, verbose=False)
    starts = {a: tuple(s) for a, s in history[0].items()}
    os.makedirs(fleet_dir, exist_ok=True)
    files = {
        "starts.json": PS.starts_json(geom, starts),
        "trajectories.json": PS.traj_json(geom, history, pitch),
        "scene.json": dict(n=n, pitch=pitch, seed=seed, mode="traj",
                           source=os.path.abspath(path), slice=meta.get("slice")),
    }
    for name, doc in files.items():
        with open(os.path.join(fleet_dir, name), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
    if verbose:
        print(f"[fms_traj] 계획 폴더 <- 궤적 첫 틱: {n}대 · {fleet_dir}")
    return n


def _main():
    if len(sys.argv) >= 4 and sys.argv[1] == "--plan-folder":
        write_plan_folder(sys.argv[2], sys.argv[3])
        return 0
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
    if cyc:
        # ★ 고리를 **실제로 뽑는다.** 「순환이다」만으로는 원인을 못 고른다 —
        #   회전 교대(PIBT 가 한 틱에 자리를 맞바꾸는 것)인지, 스윙 칸인지,
        #   앞 칸 규칙인지가 갈려야 다음 수가 정해진다.
        for row in find_cycle(adg)[:1] or [None]:
            if row is None:
                print("   ☹ 고리를 못 찾았다 (위상정렬은 실패했는데)")
                break
            print(f"   고리 길이 **{len(row)}**:")
            for uid in row:
                act = adg.actions[uid] if hasattr(adg, "actions") else None
                print(f"     {uid}  {act}")
    print("   -> 비순환이면 우리 실행층에 **그대로** 먹일 수 있다")
    return 1 if (bad or cyc) else 0


if __name__ == "__main__":
    sys.exit(_main())
