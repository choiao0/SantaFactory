# -*- coding: utf-8 -*-
"""v2/server/fetch_iwhub.py — 받는 위치를 `$ROBOT` 에서 끌어오게 한다.

무엇이 틀렸나 (2026-09-11, 팀 저장소 이관 중)
---------------------------------------------
    DEST = os.path.expanduser("~/khs/wh/warehouse/robots/iwhub/")

옛 서버 경로가 박혀 있다. 이관 후 트리는

    $W = ~/S15P21A106/2_Simulation/t3_amr
    $ROBOT = $W/robots/iwhub/iw_hub.usd          ← warehouse/ 아래가 아니다

라서, 그대로 돌리면 **옛 자리에 받고 새 자리는 계속 비어 있다.**

로봇 에셋은 `.gitignore: warehouse/robots/` 로 커밋되지 않으므로 이관 때 안
따라온다. 그래서 새 클론에서 제일 먼저 막히는 지점이 이것이다.

    ★ 없음: .../t3_amr/robots/iwhub/iw_hub.usd

무엇을 바꾸나
-------------
`DEST` 를 순서대로 찾는다.

    1. $IWHUB_DEST            직접 지정
    2. dirname($ROBOT)        paths.sh 가 정한 자리 — **이게 정답이다**
                              (main.py 가 존재를 검사하는 바로 그 경로)
    3. $WAREHOUSE/robots/iwhub
    4. <저장소>/robots/iwhub  저장소 루트에서 역산

어느 것을 골랐는지 출처와 함께 찍는다. 그래야 또 엉뚱한 데 받는 일이 없다.

받기 전에 이미 있는지도 본다 — 이미 받아 둔 트리가 옆에 있으면 몇 분짜리
재다운로드 대신 복사를 안내한다.

멱등이다. `.bak.<시각>` 을 남기고 `ast.parse` 로 검사한다.
"""
import argparse
import ast
import os
import shutil
import sys
import time

MARK = "# [patch_fetch_dest]"

OLD = '''# paths.sh 의 $WAREHOUSE/robots/iwhub 와 같은 자리여야 한다 (2026-09-08 정정).
DEST = os.path.expanduser("~/khs/wh/warehouse/robots/iwhub/")'''

NEW = MARK + ''' 받는 자리는 $ROBOT 에서 끌어온다 — 경로를 두 번 정의하지 않는다.
#   예전에는 "~/khs/wh/warehouse/robots/iwhub/" 가 박혀 있었다. 팀 저장소로
#   옮기면서 $W 가 바뀌자 옛 자리에 받고 새 자리는 계속 비어 있었다
#   (2026-09-11). main.py 가 검사하는 경로와 같은 곳에 받아야 한다.
def _dest():
    import sys as _s
    if os.environ.get("IWHUB_DEST"):
        return os.path.expanduser(os.environ["IWHUB_DEST"]), "$IWHUB_DEST"
    if os.environ.get("ROBOT"):                 # paths.sh 가 정한 자리 (정답)
        return os.path.dirname(os.path.expanduser(os.environ["ROBOT"])), "$ROBOT"
    if os.environ.get("WAREHOUSE"):
        return os.path.join(os.path.expanduser(os.environ["WAREHOUSE"]),
                            "robots", "iwhub"), "$WAREHOUSE"
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))            # v2/server/ -> 저장소 루트
    return os.path.join(root, "robots", "iwhub"), "저장소 루트 역산"


DEST, _WHY = _dest()
DEST = DEST.rstrip("/") + "/"
print(f"[iwhub] 받을 자리: {DEST}   (출처: {_WHY})", flush=True)
if not os.environ.get("ROBOT") and not os.environ.get("IWHUB_DEST"):
    print("[iwhub] ★ $ROBOT 가 없습니다 — `source paths.sh` 를 먼저 하거나\\n"
          "        IWHUB_DEST=<경로> 로 직접 주세요. 지금 자리가 맞는지 확인하세요.",
          flush=True)
if os.path.isfile(os.path.join(DEST, "iw_hub.usd")):
    print("[iwhub] 이미 있습니다 — 없는 파일만 채웁니다.", flush=True)'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="v2/server/fetch_iwhub.py")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not os.path.isfile(a.path):
        raise SystemExit(f"★ {a.path} 가 없습니다. 저장소 루트에서 실행하세요.")
    src = open(a.path, encoding="utf-8").read()
    if MARK in src:
        print("이미 적용돼 있습니다 (멱등).")
        return 0
    if src.count(OLD) != 1:
        raise SystemExit("★ 앵커를 못 찾았습니다. 파일이 이미 수정된 것 같습니다.\n"
                         "  찾던 것:\n    " + OLD.replace("\n", "\n    "))
    out = src.replace(OLD, NEW)
    ast.parse(out)
    print("  ✓ DEST 를 $ROBOT 기반으로  [ast.parse 통과]")

    if a.dry_run:
        print("\n--dry-run — 저장하지 않았습니다.")
        return 0
    shutil.copy2(a.path, a.path + time.strftime(".bak.%Y%m%d_%H%M%S"))
    open(a.path, "w", encoding="utf-8").write(out)
    print(f"\n[out] {a.path}")

    print(r"""
=============================================================
받기
=============================================================
  cd $W && source paths.sh
  python v2/server/fetch_iwhub.py
    → [iwhub] 받을 자리: .../t3_amr/robots/iwhub/   (출처: $ROBOT)
    → [iwhub] NNN개 -> ...
    → [iwhub] ok=NNN skip=0 err=0

  ls -la "$ROBOT"          # 이게 나와야 한다

=============================================================
★ 옛 트리가 아직 있으면 다시 받을 필요 없다
=============================================================
  이미 받아 둔 것이 있으면 복사가 훨씬 빠르다 (공개 S3 라 수백 개 파일이다):

    ls ~/khs/wh/warehouse/robots/iwhub/iw_hub.usd  &&  \
      mkdir -p "$(dirname "$ROBOT")"  &&  \
      cp -a ~/khs/wh/warehouse/robots/iwhub/. "$(dirname "$ROBOT")"/

  에셋은 NVIDIA 공개 S3 원본이라 판이 바뀔 일이 없다 — 복사해도 같다.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
