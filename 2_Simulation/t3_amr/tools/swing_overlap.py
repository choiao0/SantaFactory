# -*- coding: utf-8 -*-
"""**계획에 이미 겹침이 있나** — 있으면 그게 회전의 어느 칸인지까지 가른다.

왜
--
2026-09-15 주행에서 5판 중 2판이 차체 접촉으로 중단됐고, 세 사건(접촉 2 +
시드 9 의 97 mm 근접) 모두 **상대가 회전하는 쪽의 「뒤 대각」에 있었다.**

    s2  a0(70,90) h2->3   a5(69,91)   Δ(-1,+1)
    s5  a1(41,64) h2->1   a7(40,63)   Δ(-1,-1)
    s9  a9(45,87) h0->3   a6(46,88)   Δ(+1,+1)     <- 97 mm, 접촉은 안 남

뒤 대각은 `soft` 가 아니라 **`hard`** 다 (`ADG_축규칙.md` §2-3: 「로봇 몸이
실제로 쓸고 가는 칸」). `swing_cells` 에 들어 있으므로 계획기가 `now_cells`
로 막아야 한다. 그런데 안 막혔다. **`soft_hold` 문제가 아니다** — soft 칸의
유지 기간이 아니라 hard 칸이 뚫린 것이고, 층이 다르다.

그럼 어디서 뚫렸나. 두 갈래뿐이다:

    계획에 이미 있었다   -> `step_h` 가 hard 충돌을 놓쳤다.  계획기 문제
    계획은 깨끗하다      -> ADG 릴리스 타이밍.              실행 층 문제

이 도구가 앞쪽을 답한다. 겹치는 칸이 나오면 그 칸이 회전 기준으로 무엇인지
(`f0`·`f1`·`mA`·`mB`·`코대각`·`뒤대각`·`축`) 분류해서 찍는다 — 「뒤 대각이
계획에 있다」와 「엉뚱한 칸이 있다」는 고칠 곳이 다르기 때문이다.

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


def scan(geom, history):
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
            # ★ 계획기가 **예약한** 칸. `candidates_h` 의 회전 후보가 그대로
            #   `{축} | swing_cells` 다. 겹친 칸이 여기 들었나가 갈림길이다:
            #     예약 안 = 계획기가 진짜 충돌을 허용했다      -> 계획기 문제
            #     예약 밖 = 예약 모델이 실제 스윕보다 작다      -> sweep_audit 이
            #               세는 그 차이. 이산 기준으로는 합법이다
            r, c, h0 = st0[a]
            resv = frozenset({(r, c)}) | frozenset(pc.swing_cells(r, c, h0, st1[a][2]))
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


def run(seed):
    geom, free, starts, goals = pibt_scene.setup_lifelong(
        MAP, N, PITCH, seed, "cross", verbose=False)
    zone = pibt_scene.charge_zone_cells(free, geom)
    try:
        adg, _order, history, info = D.plan_and_build_lifelong(
            free, starts, goals, geom, horizon=HORIZON, seed=seed,
            order_gap=GAP, battery=BATTERY, dispatch=DISPATCH, zone_cells=zone,
            order_end=None,
            docks=pibt_scene.charge_docks(free, geom) if BATTERY else ())
    except RuntimeError as e:
        if "순환" not in str(e):
            raise
        print(f"   시드 {seed}: ADG 순환 — 계획이 안 나온다")
        return None
    hits, kinds = scan(geom, history)
    return dict(seed=seed, hits=hits, kinds=kinds, adg=adg, info=info,
                ticks=len(history) - 1)


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
        sw = r["info"].get("sweep") if isinstance(r["info"], dict) else None
        print(f"   {r['ticks']}틱 · 겹침 {len(r['hits'])}건")
        if sw:
            print(f"   sweep_audit: {sw}")
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
