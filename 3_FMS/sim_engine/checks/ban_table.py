# -*- coding: utf-8 -*-
# ============================================================
# 금지 조합표 생성기 — 회전 중 두 차체가 겹치는 (상대 위치, 상대 헤딩) 조합 (S15P21A106-251)
#
# 생성기 본체는 -277 에서 pibt/ban.py 로 옮겼다 — 커널이 회전 거부에 쓴다(geometry.configure(ban=True)).
# 여기는 표를 찍는 CLI 와, 예전 이름으로 부르던 곳(tests/test_ban_table.py · checks/turn_clearance.py)을 위한
# 재내보내기만 남긴다. 규약·한계는 pibt/ban.py 머리말.
#
# 사용: python checks/ban_table.py            # 표를 찍는다
# ============================================================
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pibt.ban import (DIRS, FRONT, HALF_W, REAR, banned, build_table, corners,  # noqa: E402,F401
                      overlap, rear_cell)

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    t = build_table()
    print("pitch 1.0 · 여유 0.05 · 기종 (%.2f, %.2f, %.2f)" % (FRONT, REAR, HALF_W * 2))
    for sgn, nm in ((+1, "좌"), (-1, "우")):
        ent = sorted(t[sgn])
        print("  회전 %s (%d)  %s" % (nm, len(ent), "  ".join("(%d,%d)h%d" % (c[0], c[1], h) for c, h in ent)))
    print("pitch 1.2 · 여유 0.05 -> %d개" % sum(len(v) for v in build_table(1.2).values()))
    print("pitch 1.0 · 여유 0    -> %d개" % sum(len(v) for v in build_table(1.0, 0.0).values()))
