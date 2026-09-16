# -*- coding: utf-8 -*-
"""**계획에 이미 겹침이 있나** — 있으면 그게 회전의 어느 칸인지까지 가른다.

왜
--
2026-09-15 주행에서 5판 중 2판이 차체 접촉으로 중단됐다. 주행 로그의 ADG
진단이 접촉 순간을 그대로 준다:

    agent0 실행중 A0#84  turn(70, 90, 2) -> (70, 90, 1) @t780
    agent5 대기    A5#179 move(69, 91, 1) -> (69, 92, 1) @t783
                                                선행 미완 -> agents [4]

a0 회전의 guard 는 `{f0(71,90), f1(70,91), mA(71,89), mB(69,91)}` 이고
**a5 의 축이 `mB` 안**이다. `soft` 의 뜻이 「상대의 **축**이 못 들어온다」
이므로 규칙이 막아야 하는 배치인데 안 막혔다.

> ★ 초판은 이 칸을 「뒤 대각」이라 적고 `soft_hold` 를 기각했다. **틀렸다** —
>   yaw 에서 헤딩을 역산하며 `heading_offset` 을 2 로 봤는데 실제는 0 이다
>   (`GEOM_KW`). ADG 로그의 헤딩이 정답이고, 그걸로 다시 계산하면 `mB` 다.

어디서 뚫렸나. 두 갈래다:

    계획에 이미 있었다   -> `_soft_blocked` 가 거부했어야 한다.  계획기 문제
    계획은 깨끗하다      -> 회전 5틱 중 2~5틱이 무방비.          `soft_hold`

`scan_guard` 가 앞쪽을 답한다 — 규칙의 문장 그대로 **`guard ∩ 남의 축`** 을
회전의 **5틱 창 내내** 센다. `scan()`(=`swept ∩ body`)으로는 못 본다:
`mA`·`mB` 는 pitch 1.0 에서 실제 스윕 밖(0/8)이라 `swept` 에 안 들어간다.

★ `test_lifelong_battery.py` 로는 이걸 못 본다. `main(n=12, pitch=1.2,
  horizon=315, seeds=(1,4,16,18,21))` 이 하드코딩이고 환경변수를 안 읽어서
  pitch 1.2 · 옛 틱 모델(315틱 · order_gap 15)로 돈다. 2026-09-15 에
  `PIBT_PITCH=1.0 PIBT_SEED=2` 를 줬는데 통째로 무시됐다.

쓰는 법
-------
    source paths.sh
    PIBT_FRONT_RULE=4 PIBT_PITCH=1.0 SEEDS=2,5,9 python tools/swing_overlap.py

    설정은 `run_record.sh` 와 맞춰 둔다 (배터리 끔 · 배차 fms · 1260틱 ·
    주기 60 · 존복귀 켬). 다르게 재면 주행과 비교가 안 된다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))

import numpy as np                                      # noqa: E402
import pibt_core_v2 as pc                               # noqa: E402
from pibt_core import TURN_TICKS                        # noqa: E402
import isaac_drive as D                                 # noqa: E402
import pibt_scene                                       # noqa: E402

MAP = os.environ["MAP"]
N = int(os.environ.get("N", "12"))
PITCH = float(os.environ.get("PIBT_PITCH", "1.0"))
SEEDS = [int(x) for x in os.environ.get("SEEDS", "2,5,9").split(",")]
HORIZON = int(os.environ.get("HORIZON", "1260"))
GAP = int(os.environ.get("GAP", "60"))
BATTERY = os.environ.get("BATTERY", "0") not in ("0", "", "no", "off")
DISPATCH = os.environ.get("PIBT_DISPATCH", "fms")
FRONT_RULE = os.environ.get("PIBT_FRONT_RULE", "(안 줌 → 규칙 꺼짐)")
TOP = int(os.environ.get("TOP", "12"))


def classify(s0, s1, cell):
    """회전 `s0->s1` 기준으로 `cell` 이 무엇인가.

    d1 = DIRS[h0], d2 = DIRS[h1] 일 때
        축 (r)            자기 칸
        f0 (r+d1)         앞 칸 — 옛 헤딩 쪽      soft
        f1 (r+d2)         앞 칸 — 새 헤딩 쪽      soft
        mA (r+d1-d2)      섞임 대각               soft (4칸에서만)
        mB (r-d1+d2)      섞임 대각               soft (4칸에서만)
        코대각 (r+d1+d2)   규칙에서 **뺐다** (§2-2)
        뒤대각 (r-d1-d2)   몸이 쓸고 간다 — **hard** (§2-3)
    """
    (r, c, h0), (_, _, h1) = s0, s1
    d1, d2 = pc.DIRS[h0], pc.DIRS[h1]
    named = {
        (r, c): "축",
        (r + d1[0], c + d1[1]): "f0",
        (r + d2[0], c + d2[1]): "f1",
        (r + d1[0] - d2[0], c + d1[1] - d2[1]): "mA",
        (r - d1[0] + d2[0], c - d1[1] + d2[1]): "mB",
        (r + d1[0] + d2[0], c + d1[1] + d2[1]): "코대각",
        (r - d1[0] - d2[0], c - d1[1] - d2[1]): "뒤대각",
    }
    return named.get(tuple(cell), "기타")


def scan(geom, history, cells_hist):
    """틱마다 「A 가 쓸고 가는 칸」 x 「B 의 몸」 교집합을 센다.

    ★ `swept_cells(s0, s1)` 은 **실제 스윕**이다 (`cells_hist` 의 예약이
      아니라). 예약이 스윕보다 모자라면 이산 기준으로는 합법인데 연속
      실행에서 닿는다 — `sweep_audit` 이 그 차이를 따로 센다.
    """
    hits, kinds = [], {}
    for t in range(len(history) - 1):
        st0, st1 = history[t], history[t + 1]
        agents = sorted(st0)
        swept = {a: geom.swept_cells(st0[a], st1[a]) for a in agents}
        # ★ 합집합과 교집합을 둘 다 쓴다.
        #   합집합 = 틱 양끝 중 **한쪽**에라도 몸이 있었다. B 가 그 틱에 빠져
        #            나가는 중일 수도 있어 이것만으로는 단정 못 한다.
        #   교집합 = 틱 **내내** 있었다. 이건 빠져나갈 여지가 없다.
        body = {a: frozenset(pc.occupied(st0[a])) | frozenset(pc.occupied(st1[a]))
                for a in agents}
        held = {a: frozenset(pc.occupied(st0[a])) & frozenset(pc.occupied(st1[a]))
                for a in agents}
        for a in agents:
            # 회전만 본다. 전진은 스윕이 두 칸 직선이라 성격이 다르다.
            if st0[a][:2] != st1[a][:2] or st0[a][2] == st1[a][2]:
                continue
            # ★ 계획기가 **실제로 예약한** 칸 — `cells_hist` 에서 그대로 읽는다.
            #
            #   처음에는 `{축} | pc.swing_cells(...)` 로 다시 계산했는데 **틀렸다**
            #   (2026-09-15). `sweep_audit` 이 찍는 예약과 부호가 반대로 나온다:
            #       turn (54,100,3)->(54,100,0)
            #         cells_hist   [(53,100), (53,101), (54,100), (54,101)]
            #         재계산        [(54,100), (54,101), (55,100), (55,101)]
            #   `heading_offset` 계열의 프레임 차이로 보이는데, 어느 쪽이든
            #   **판정에 쓸 것은 실제 예약**이다. 재계산으로 라벨을 붙였다가
            #   「계획기가 자기 hard 칸에 남을 들였다」는 없는 결론을 냈다.
            resv = frozenset(map(tuple, cells_hist[t].get(a, ())))
            for b in agents:
                if b == a:
                    continue
                for cell in swept[a] & body[b]:
                    k = classify(st0[a], st1[a], cell)
                    inres = tuple(cell) in resv
                    stay = cell in held[b]          # 틱 내내 거기 있었나
                    key = (f"{k}{'(예약안)' if inres else '(예약밖)'}"
                           f"{'(상주)' if stay else ''}")
                    kinds[key] = kinds.get(key, 0) + 1
                    hits.append((t, a, b, cell, k, inres, stay))
    return hits, kinds


def scan_guard(geom, history):
    """★ 규칙 위반을 **정면으로** 센다 — `guard ∩ 남의 축`.

    `scan()` 은 `swept[a] ∩ body[b]` 를 본다. 그런데 4칸 규칙의 `mA`·`mB` 는
    pitch 1.0 에서 **실제 스윕 밖**이다 (`ADG_축규칙.md` §2-3 표: 0/8).
    그래서 `swept[a]` 에 애초에 안 들어가고, **`scan()` 은 mA·mB 위반을
    구조적으로 못 본다** — 실제로 세 시드 출력에 mA·mB 가 한 번도 안 나왔다.

    규칙의 문장은 「`guard` 에 **상대의 축**이 들어오면 안 된다」다. 그러니
    그대로 재야 한다. 2026-09-16 주행에서 a5 의 축이 a0 회전의 `mB` 에
    있었는데 `scan()` 이 못 잡은 자리가 이것이다.

    `guard` 는 계획기가 쓰는 것과 같은 함수에서 받는다 (`RobotGeom.front_cells`
    -> `pibt.geometry.front_cells`). 여기서 다시 구현하면 정의가 두 벌이 된다.
    """
    hits, kinds = [], {}
    for t in range(len(history) - 1):
        st0, st1 = history[t], history[t + 1]
        agents = sorted(st0)
        for a in agents:
            s0, s1 = st0[a], st1[a]
            if s0[:2] != s1[:2] or s0[2] == s1[2]:      # 회전만
                continue
            guard = frozenset(geom.front_cells(s0, s1))
            if not guard:                                # 규칙이 꺼져 있다
                continue
            # ★ 회전은 **5틱**이다. `lifelong` 이 회전 시작 틱에 헤딩을 바꾸고
            #   `busy = turn_ticks - 1` 로 4틱 더 잡는다. 그러니 guard 도 그
            #   창 내내 유효해야 한다.
            #
            #   초판은 헤딩이 바뀌는 **한 틱만** 봤다 — `soft_next` 가 1틱만
            #   사는 것과 똑같은 맹점이라, 2~5틱째에 들어와 앉은 로봇을
            #   구조적으로 못 봤다. 그 상태로 「0건 = 계획은 결백」을 찍을
            #   뻔했다 (2026-09-16).
            for dt in range(TURN_TICKS):
                tt = t + dt
                if tt + 1 >= len(history):
                    break
                q0, q1 = history[tt], history[tt + 1]
                # 회전이 끝났으면(칸이나 헤딩이 또 바뀌었으면) 창을 닫는다.
                if q0.get(a, s1)[:2] != s0[:2]:
                    break
                for b in agents:
                    if b == a:
                        continue
                    # 「축」은 상대의 **칸 좌표**다 (몸 전체가 아니라).
                    axle = {tuple(q0[b][:2]), tuple(q1[b][:2])}
                    for cell in guard & frozenset(axle):
                        k = classify(s0, s1, cell)
                        stay = tuple(q0[b][:2]) == tuple(q1[b][:2]) == tuple(cell)
                        key = (f"{k}{'(상주)' if stay else ''}"
                               f"{'(1틱째)' if dt == 0 else f'({dt + 1}틱째)'}")
                        kinds[key] = kinds.get(key, 0) + 1
                        hits.append((tt, a, b, cell, k, dt, stay))
    return hits, kinds


def run(seed):
    """`run_lifelong` 을 직접 불러 **`cells_hist` 까지** 받는다.

    `plan_and_build_lifelong` 은 `(adg, order, history, info)` 만 돌려주고
    `cells_hist` 는 안 준다. 그런데 실제 예약이 거기 있으므로 한 겹 벗겨서
    직접 부른다 — `isaac_drive.py:2404` 의 호출을 그대로 옮긴 것이다.
    """
    from lifelong import Kernel, run_lifelong                # noqa: E402
    geom, free, starts, goals = pibt_scene.setup_lifelong(
        MAP, N, PITCH, seed, "cross", verbose=False)
    zone = pibt_scene.charge_zone_cells(free, geom)

    kw = {}
    if BATTERY:
        from battery import BatteryKernel                    # noqa: E402
        kw = dict(kernel_cls=BatteryKernel,
                  kernel_kw=dict(docks=list(pibt_scene.charge_docks(free, geom)),
                                 pitch=geom.pitch, seed=seed))
    if DISPATCH != "fms":
        from dispatch import with_policy                     # noqa: E402
        kw["kernel_cls"] = with_policy(kw.get("kernel_cls") or Kernel, DISPATCH)
        kw.setdefault("kernel_kw", {})

    history, cells_hist, li = run_lifelong(
        free, starts, goals, horizon=HORIZON, seed=seed, order_gap=GAP,
        shifts=("in", "out", "out"), zone_cells=zone, order_end=None, **kw)

    sweep = D.sweep_audit(geom, history, cells_hist)
    chains, _order, _stats = extract(history, geom, li)
    adg = D.build_adg(chains)
    cyclic = adg.topological_order() is None

    hits, kinds = scan(geom, history, cells_hist)
    ghits, gkinds = scan_guard(geom, history)
    return dict(seed=seed, hits=hits, kinds=kinds, ghits=ghits, gkinds=gkinds,
                sweep=sweep, cyclic=cyclic,
                tasks=li.get("tasks_done"), ticks=len(history) - 1)


def extract(history, geom, li):
    return D.extract_actions(history, geom, task_start=li.get("task_start"))


def main():
    print(f"계획 겹침 검사 — n {N} · pitch {PITCH} · {HORIZON}틱 · 주기 {GAP}"
          f" · 배터리 {'켬' if BATTERY else '끔'} · 배차 {DISPATCH}")
    print(f"  앞 칸 규칙 PIBT_FRONT_RULE={FRONT_RULE}   ← 주행은 4 로 돈다")
    print("  ★ 회전만 본다. 「A 의 실제 스윕」과 「B 의 몸」이 같은 틱에 겹치나.")

    for seed in SEEDS:
        print(f"\n══ 시드 {seed} " + "═" * 50)
        r = run(seed)
        if r is None:
            continue
        sw = r["sweep"]
        print(f"   {r['ticks']}틱 · 태스크 {r['tasks']}"
              f" · ADG {'★순환' if r['cyclic'] else '비순환'}"
              f" · 겹침 {len(r['hits'])}건")
        if sw:
            print(f"   sweep_audit 예약부족 {sw['short']}/{sw['total']}"
                  f" ({100.0 * sw['short'] / max(1, sw['total']):.1f}%)  {sw['by_kind']}")
        if not r["hits"]:
            print("   -> 계획은 깨끗하다. 접촉은 **실행 층**에서 났다는 뜻이다.")
            continue
        print(f"   칸 종류별: {r['kinds']}")
        # 뒤대각이 있으면 그게 주행에서 본 것과 같은 모양이다.
        back_in = sum(v for k, v in r["kinds"].items()
                      if k.startswith("뒤대각(예약안)"))
        if back_in:
            print(f"   ★ 뒤 대각이 **예약 안에** 있는데 겹쳤다 {back_in}건 —")
            print("     계획기가 자기가 예약한 hard 칸에 남을 들였다는 뜻이다.")
        # --- ★ 규칙 위반 정면 검사 -------------------------------------
        print()
        print(f"   ★ guard ∩ 남의 축 — **규칙이 금지하는 배치**: {len(r['ghits'])}건")
        if r["ghits"]:
            print(f"      종류별: {r['gkinds']}")
            print(f"      {'틱':>6}{'A':>4}{'B':>4}  {'칸':>10}  종류")
            for t, a, b, cell, k, dt, stay in r["ghits"][:TOP]:
                print(f"      {t:>6}{a:>4}{b:>4}  {str(tuple(cell)):>10}  {k:<8}"
                      f"{'  상주' if stay else '  통과중'}  {dt + 1}틱째")
            if len(r["ghits"]) > TOP:
                print(f"      ... 외 {len(r['ghits']) - TOP}건")
            print("      -> ★ 계획이 규칙을 어긴 배치를 만들었다. `_soft_blocked` 가")
            print("         거부했어야 하는 자리다.")
        else:
            print("      -> 계획은 규칙을 지킨다. 위반은 **실행 층**에서 생긴 것이다.")

        print(f"\n   {'틱':>6}{'A':>4}{'B':>4}  {'칸':>10}  종류")
        for t, a, b, cell, k, inres, stay in r["hits"][:TOP]:
            print(f"   {t:>6}{a:>4}{b:>4}  {str(tuple(cell)):>10}  {k:<8}"
                  f"{'예약 안 ★' if inres else '예약 밖'}"
                  f"{'  상주' if stay else '  통과중'}")
        if len(r["hits"]) > TOP:
            print(f"   ... 외 {len(r['hits']) - TOP}건")
    print()
    print("* 겹침 0 이면 계획기는 결백하다 — ADG 릴리스 타이밍을 봐야 한다.")
    print("* 「뒤대각」이 나오면 계획기가 hard 충돌을 놓친 것이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
