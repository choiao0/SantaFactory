# -*- coding: utf-8 -*-
"""계획 격자 기본값이 저장소 안에서 **한 값**인가 (2026-09-22, 0단계).

왜 이 테스트가 있나
-------------------
`PIBT_PITCH` 를 **안 주고** 부르는 경로가 파일마다 다른 값으로 섰다. 2026-09-17
에 한 번 터졌다 — `REPLAN=1 bash run_record.sh` 가

    계획   amr/path/pibt_h.PITCH 기본값 1.2  (PIBT_PITCH 가 아직 없다)
    주행   run_record.sh 의 PIBT_PITCH=1.0

로 갈렸고, 충전존 시작 슬롯이 pitch 에서 나오므로 **무대 스폰이 주행 계획과
다른 자리**가 됐다. 추종기가 자기 경로를 못 잡는 그 실패 모드다.
**오류는 하나도 안 났다** (경위: `run_record.sh:160-172`).

같은 사고가 `edge/recorder.py` 에서도 났다 — `PLAN_PITCH_DEFAULT_M` 이 1.2 라
창을 20 % 짧게 계획했다 (2026-09-21 고침).

그래서 값을 고치는 것으로는 안 끝난다. **새로 생기는 파일**이 다시 1.2 를
들고 오는 것을 막아야 한다. 이 테스트는 값을 나열하지 않고 **소스를 훑어서**
기본값을 모은 뒤 전부 같은지 본다.

무엇을 안 보나
--------------
`PITCHES` 같은 **스윕 목록**과, 기본값이 아니라 명시로 1.2 를 넘기는 자리는
대상이 아니다 (`_ALLOW` 참고).

단독 실행도 된다:  python edge/tests/test_pitch_default.py
"""
import os
import re
import sys

T3AMR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PLAN_PITCH_M = 1.0          # ← 이 저장소의 계획 격자. 바꾸려면 여기 하나만.

# 기본값이 적히는 **모양**들. 각 패턴은 값 하나를 그룹 1 로 잡는다.
_PATTERNS = (
    # os.environ.get("PIBT_PITCH", "1.0") / os.environ.get("PITCH", "1.0")
    re.compile(r'environ\.get\(\s*"(?:PIBT_)?PITCH"\s*,\s*"([0-9.]+)"\s*\)'),
    # ap.add_argument("--pitch", type=float, default=1.0 ...)
    re.compile(r'"--pitch"\s*,\s*type=float\s*,\s*default=([0-9.]+)'),
    # ${PIBT_PITCH:-1.0}  (셸)
    re.compile(r'PIBT_PITCH:-([0-9.]+)'),
    # RobotGeom 의 pitch: float = 1.0
    re.compile(r'^\s*pitch:\s*float\s*=\s*([0-9.]+)', re.M),
    # amr/path/pibt_h.py 의 PITCH = 1.0 / edge/recorder.py 의 PLAN_PITCH_DEFAULT_M
    re.compile(r'^(?:PITCH|PLAN_PITCH_DEFAULT_M)\s*=\s*([0-9.]+)', re.M),
)

# 훑지 않을 곳
_SKIP_DIRS = ("docs", "out", "data", "__pycache__", ".git", "deploy/data")

# 기본값이 아니라서 빼는 자리 — (경로 조각, 그 줄에 들어 있는 글귀)
_ALLOW = (
    # 기본값을 **덮어쓰는** 것이 목적인 테스트
    ("edge/tests/test_recorder.py", "PIBT_PITCH"),
    # pitch 를 여러 개 훑는 도구. 목록이지 기본값이 아니다
    ("tools/axle_rule.py", "PITCHES"),
    ("tools/try_swing5.py", "PITCHES"),
    # ★ WPPL 로드맵의 **정점 간격**이다 (2.4 m). PIBT 계획 격자와 다른 물건이고,
    #   `PLAN_SAFETY_DIST`(2.365) 에서 나온 값이라 1.0 으로 내리면 안 된다.
    #   같은 이름(PITCH)을 쓰는 것이 헷갈림의 원인이라 여기 적어 둔다.
    ("amr/make_path/lattice.py", "PITCH = 2.4"),
)


def _allowed(rel, line):
    return any(a in rel.replace("\\", "/") and b in line for a, b in _ALLOW)


def collect():
    """(상대경로, 줄번호, 줄, 값) 목록."""
    found = []
    for root, dirs, files in os.walk(T3AMR):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if not name.endswith((".py", ".sh")):
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, T3AMR)
            if any(s in rel.replace("\\", "/") for s in _SKIP_DIRS):
                continue
            try:
                with open(full, encoding="utf-8") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            for pat in _PATTERNS:
                for m in pat.finditer(text):
                    lineno = text.count("\n", 0, m.start()) + 1
                    line = text.splitlines()[lineno - 1].strip()
                    if _allowed(rel, line):
                        continue
                    found.append((rel, lineno, line, float(m.group(1))))
    return found


def test_plan_pitch_default_is_one_value():
    found = collect()
    assert found, "기본값을 하나도 못 찾았다 — 패턴이 낡았다"
    bad = [f for f in found if abs(f[3] - PLAN_PITCH_M) > 1e-9]
    assert not bad, (
        "계획 격자 기본값이 %.2f 가 아닌 곳이 %d 군데다. "
        "`PIBT_PITCH` 없이 부르면 여기서 다른 격자로 선다:\n%s"
        % (PLAN_PITCH_M, len(bad),
           "\n".join("  %s:%d  %s   -> %s" % (r, n, l, v) for r, n, l, v in bad))
    )


def test_shell_and_edge_agree():
    """셸·엣지·계획기 셋은 **이름으로** 확인한다 — 위 훑기가 못 보면 여기서 걸린다."""
    import io
    want = {
        "run_record.sh": r'PIBT_PITCH:-([0-9.]+)',
        os.path.join("edge", "recorder.py"): r'^PLAN_PITCH_DEFAULT_M\s*=\s*([0-9.]+)',
        os.path.join("amr", "path", "pibt_h.py"): r'^PITCH\s*=\s*([0-9.]+)',
    }
    for rel, pat in want.items():
        full = os.path.join(T3AMR, rel)
        assert os.path.exists(full), "%s 가 없다 — 경로가 바뀌었으면 이 테스트도 고친다" % rel
        with io.open(full, encoding="utf-8") as fh:
            m = re.search(pat, fh.read(), re.M)
        assert m, "%s 에서 계획 격자 기본값을 못 찾았다" % rel
        assert abs(float(m.group(1)) - PLAN_PITCH_M) < 1e-9, \
            "%s 의 기본값이 %s 다 (기대 %.2f)" % (rel, m.group(1), PLAN_PITCH_M)


if __name__ == "__main__":
    rows = collect()
    print("계획 격자 기본값 %d 군데" % len(rows))
    for r, n, l, v in sorted(rows):
        print("  %-42s:%-5d %s" % (r, n, v))
    ok = True
    for fn in (test_plan_pitch_default_is_one_value, test_shell_and_edge_agree):
        try:
            fn()
            print("[PASS] %s" % fn.__name__)
        except AssertionError as e:
            ok = False
            print("[FAIL] %s\n%s" % (fn.__name__, e))
    sys.exit(0 if ok else 1)
