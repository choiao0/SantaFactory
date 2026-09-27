# -*- coding: utf-8 -*-
"""시드별 로그의 `[회전분포]` 를 **하나로 합친다** (S15P21A106-240).

왜 필요한가
-----------
6시간 한 판으로는 분포가 안 모인다 — 첫 사고에서 판이 죽으므로 표본이
350초 판과 같아진다. 그래서 시드를 여러 개 돌리는데, 그러면 시드마다 표가
따로 나온다. 손으로 더하면 틀린다.

판정은 하나뿐이다:

    **틈 `150~300`** 이 비어 있나

    비었다   ★ 이봉 — 평상(회전 사슬 천장 104 mm)과 사고(a6 382 mm) 사이가
             끊겨 있다. 드문 사고라 시드를 버리는 게 싸다
    찼다     ★ 연속 — 관문을 조금만 조여도 자주 걸린다.  A·C 가 필요하다

☹ 처음에는 `50~80` 과 `80~100` 이 비었나로 판정했는데 **거기는 평상 자리다**
  (2026-09-17 정정). 평상 천장이 `tol.pos + 밀림` 이 아니라 **회전 사슬**을
  타서 68 / 86 / 104 mm 로 올라간다. 시드 2 실측이 `50~80` 76건(48.7 %) ·
  `80~100` 1건인데 접촉 0 으로 완주했다 — 차 있는 것이 정상이다.
  그 기준으로 읽었다가 정상 분포를 「연속」으로 오독했다.

  `100~150` 은 3연속 회전(<=104)과 사고가 겹치는 **경계**라 단정하지 않는다.

★ 합치는 것은 **버킷 수**다. 중앙·p95 는 시드마다 따로 나온 값이라 그냥
  더하면 안 된다 — 여기서는 버킷에서 다시 추정하고, 원래 값은 시드별로
  나란히 보여 준다. 그래야 「합친 중앙값」이 가짜인 것이 안 숨는다.

쓰는 법
-------
    python tools/turn_hist_merge.py $LOGS/hist_s*.log
"""
import re
import sys

# ★ **틈** — 여기가 비어 있으면 이봉이다.
#
#   ☹ 처음에 `(80, 100, 150)` 으로 뒀는데 **80 과 100 은 평상 자리**였다.
#     평상 천장이 `tol.pos + 밀림` 이 아니라 **회전 사슬**을 탄다:
#
#         사슬 1번째   50 + 18 =  68 mm
#         사슬 2번째   68 + 18 =  86 mm   <- 시드 2 실측 최대 85.37
#         사슬 3번째   86 + 18 = 104 mm
#
#     회전의 10.7 %가 회전 뒤에 온다 (180도 = 회전 둘). 그래서 `80~100` 은
#     2연속 자리라 조금 차는 것이 정상이고, `100~150` 은 3연속(<=104)과
#     사고가 **겹치는 경계 구간**이다.
#
#   a6 사고는 382 mm 다. 확실히 빈 곳은 `150~300` 뿐이다.
GAP = (150,)
# 경계 — 3연속 회전(<=104)이 여기 들어올 수 있어 단정하지 않는다.
EDGE = (100,)

HDR = re.compile(r"회전\s+([\d,]+)건.*?중앙\s+([\d.]+).*?p95\s+([\d.]+)"
                 r".*?최대\s+([\d.]+)\s*mm(?:.*?초과\s+([\d,]+)건)?")
ROW = re.compile(r"^\s*([\d]+)~(\d+|inf)\s+([\d,]+)\s+([\d.]+)%")


def parse(path):
    """그 로그의 **마지막** `[회전분포]` 덩어리를 돌려준다."""
    head, rows, cur = None, None, None
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError as e:
        print(f"  ! {path}: {e}")
        return None
    for ln in lines:
        if "[회전분포]" not in ln:
            continue
        body = ln.split("[회전분포]", 1)[1]
        m = HDR.search(body)
        if m:
            head = (int(m.group(1).replace(",", "")), float(m.group(2)),
                    float(m.group(3)), float(m.group(4)),
                    int((m.group(5) or "0").replace(",", "")))
            cur = []
            continue
        m = ROW.match(body)
        if m and cur is not None:
            cur.append((int(m.group(1)), m.group(2),
                        int(m.group(3).replace(",", ""))))
            # 마지막 칸까지 읽었으면 확정
            if m.group(2) == "inf":
                rows = cur
    return (head, rows) if head and rows else None


def main(paths):
    got = []
    for p in paths:
        r = parse(p)
        if r:
            got.append((p, r))
        else:
            print(f"  ! {p}: `[회전분포]` 를 못 찾았다 (판이 그 전에 죽었나)")
    if not got:
        return 1

    print("  ── 시드별 ──")
    print(f"  {'로그':<28}{'회전':>7}{'중앙':>9}{'p95':>9}{'최대':>9}{'초과':>7}")
    tot = {}
    order = []
    n_all = 0
    mx_all = 0.0
    over_all = 0
    for p, (h, rows) in got:
        n, med, p95, mx, over = h
        n_all += n
        mx_all = max(mx_all, mx)
        over_all += over
        print(f"  {p.split('/')[-1]:<28}{n:>7,}{med:>8.2f}{p95:>9.2f}"
              f"{mx:>9.2f}{over:>7}")
        for lo, hi, cnt in rows:
            k = (lo, hi)
            if k not in tot:
                tot[k] = 0
                order.append(k)
            tot[k] += cnt

    print()
    print(f"  ── 합계 · 회전 {n_all:,}건 · 최대 {mx_all:.2f} mm · "
          f"기준선 초과 {over_all}건 ──")
    top = max(tot.values()) or 1
    # 버킷에서 중앙값을 추정한다 (진짜 중앙이 아니다 — 위 시드별 표를 볼 것)
    acc, med_bin = 0, None
    for k in order:
        acc += tot[k]
        if med_bin is None and acc >= n_all / 2:
            med_bin = k
    for lo, hi in order:
        cnt = tot[(lo, hi)]
        bar = "#" * min(44, int(44.0 * cnt / top))
        mark = "  <- 중앙 구간" if (lo, hi) == med_bin else ""
        # ★ **틈**은 150~300 이다 (2026-09-17 정정). 50~80 은 평상 무리의 일부다 —
        #   도착 오차(tol.pos 50)에 회전 밀림이 얹힌 자리라 차 있는 것이 정상이다.
        #   거기에 「사이가 찼다」를 붙였더니 정상 분포를 연속으로 오독했다.
        if lo in GAP and cnt:
            mark += "  ★ 틈이 찼다"
        print(f"  {lo:>4}~{hi:<4} {cnt:>7,} {100.0 * cnt / n_all:5.1f}%  "
              f"{bar}{mark}")

    normal = sum(tot.get(k, 0) for k in order if k[0] < 100)
    edge = sum(tot.get(k, 0) for k in order if k[0] in EDGE)
    gap = sum(tot.get(k, 0) for k in order if k[0] in GAP)
    far = sum(tot.get(k, 0) for k in order if k[0] >= 300)
    print()
    print("  ── 판정 ──")
    print(f"  평상 (<100 mm)   {normal:>6,}건 {100.0 * normal / n_all:5.1f} %"
          f"   사슬 천장 104")
    print(f"  경계 (100~150)   {edge:>6,}건 {100.0 * edge / n_all:5.1f} %"
          f"   3연속 회전이 여기 올 수 있다")
    print(f"  ★ 틈 (150~300)   {gap:>6,}건 {100.0 * gap / n_all:5.1f} %"
          f"   <- 이게 비어 있나가 판정이다")
    print(f"  사고 (>=300)     {far:>6,}건 {100.0 * far / n_all:5.1f} %")
    print()
    # ★ 판정은 **틈**으로 한다. 「100 을 넘는 게 있나」로 하면, 틈이 비고 멀리
    #   하나만 있는 **정확히 이봉인 경우**를 연속으로 잘못 읽는다 (2026-09-17
    #   합성 자료에서 실제로 그랬다).
    if gap == 0 and far > 0:
        print("  ★ **이봉이다** — 평상(<=104, 사슬 천장)과 사고 사이가 끊겨 있다.")
        print("    350초 판에서는 워치독이 끊고 그 시드를 버리는 편이 싸다.")
        print("    ★ 다만 **6시간 연속 운전은 다르다** — 한 번만 나도 함대가")
        print("      영구히 얼어 남은 시간이 통째로 날아간다. 그쪽이 요구사항이면")
        print("      빈도와 무관하게 복구 수단이 필요하다 (E 는 닫혔고 A 가 남았다).")
    elif gap == 0:
        print("  ~ 사고가 한 건도 안 났다. 표본이 모자라거나 이 시드들이 깨끗하다.")
        print("    시드를 더 돌려야 판정이 선다.")
    else:
        print("  ☠ **연속이다** — 틈(150~300)이 차 있다.")
        print("    관문을 조금만 조여도 자주 걸린다는 뜻이고, 버릴 시드가 는다.")
        print("    A(복구 기동) 또는 C(재계획)가 실제로 필요하다.")
    if edge:
        print()
        print(f"  ※ 경계 `100~150` 에 {edge}건 있다. 3연속 회전(<=104 mm)인지")
        print("    사고인지는 이 표로 못 가른다 — 로그의 `turn_gate_over` 와")
        print("    워치독 줄(`uid=… cells=…`)을 봐야 한다.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1:]))
