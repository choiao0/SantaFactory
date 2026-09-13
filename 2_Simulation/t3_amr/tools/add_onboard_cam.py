# -*- coding: utf-8 -*-
"""가장 많이 움직인 AMR 에 **진행방향을 보는 카메라**를 단다 (S15P21A106-200).

    python tools/add_onboard_cam.py --stage $STAGE/pibt12.usd --rec $OUT/rec_pibt12.npz
    python tools/add_onboard_cam.py ... --amr 7 --mode chase

Isaac 이 필요 없다. `pxr` 만 쓰므로 몇 초면 끝난다 — 카메라 위치를 바꿔 가며
여러 번 돌려도 싸다. 마지막 줄에 카메라 prim 경로를 찍으므로 셸에서 받아
`PIBT_CAMERA` 로 넘기면 된다 (`run_onboard.sh` 가 그렇게 한다).

[★ 카메라는 반드시 **링크** 밑에 단다]
`/World/Robots/amr_N` 은 ArticulationRoot Xform 이고 **PhysX 가 그걸 안 움직인다.**
자세는 각 링크 prim(`chassis`·`left_wheel`·…)에 쓴다. 루트에 달면 로봇만 달리고
카메라는 출발 자리에 남는다 — 선반에서 똑같이 당했다 (2026-09-13).

[좌표 규약]
로봇 로컬: 원점 = 구동축, **+X 가 전진** (`heading_offset=0`), z 는 로봇 로컬이다.
`chassis` 의 로컬 변환이 항등이라 그 밑에서는 로봇 로컬 좌표를 그대로 쓴다.
이 스크립트의 눈높이·목표는 **바닥 기준**으로 적고 WHEEL_R 을 빼서 넣는다.

[어느 로봇이 '가장 많이 움직였나']
자세 기록(`rec_*.npz`)에서 **이동 경로 길이**를 로봇별로 적분한다. 완료 태스크
수가 아니라 실제 주행 거리다 — 화면에 담고 싶은 것은 "많이 돌아다닌 로봇" 이다.
기록이 없으면 `--amr` 로 직접 준다.
"""
import argparse
import math
import os
import sys

import numpy as np
from pxr import Gf, Usd, UsdGeom

WHEEL_R = 0.081        # build_amr_scene_v2.py 와 같은 값. 로봇 prim 의 z

# 시점 — (눈, 목표, 초점거리[mm]). 로봇 로컬 · **바닥 기준** z.
VIEWS = {
    # 코앞에서 진행방향. 선반(앞면 0.390) 보다 앞에 두어 시야가 안 막힌다.
    "nose":  ((0.55, 0.0, 1.20), (6.0, 0.0, 0.45), 20.0),
    # 뒤 위에서 따라간다. 로봇과 진행방향을 같이 담는다.
    "chase": ((-3.2, 0.0, 2.60), (4.0, 0.0, 0.40), 24.0),
    # 바로 위. 주변 로봇과의 간격을 보고 싶을 때.
    "top":   ((-0.3, 0.0, 6.50), (2.2, 0.0, 0.00), 20.0),
}


def busiest(rec_path, n_expect=None):
    """자세 기록에서 주행 거리가 가장 긴 로봇. 반환 (index, 거리표)."""
    z = np.load(rec_path)
    pose = z["pose"].astype(np.float64)          # (N, R, 3) = x, y, yaw
    d = np.hypot(np.diff(pose[:, :, 0], axis=0),
                 np.diff(pose[:, :, 1], axis=0)).sum(axis=0)
    if n_expect is not None and len(d) != n_expect:
        print(f"  · 기록의 로봇 수 {len(d)} != 씬의 {n_expect} — 기록 쪽을 따른다",
              file=sys.stderr)
    return int(np.argmax(d)), d


def look_at_local(stage, path, eye, tgt, focal):
    """build_amr_scene_v2.py:look_at 과 **같은 수식**. 어긋나면 다른 데를 본다.

    USD 카메라는 자기 좌표계의 -Z 를 본다. 행렬 행이 (right, up, -forward, eye).
    """
    cam = UsdGeom.Camera.Define(stage, path)
    cam.CreateFocalLengthAttr(focal)
    cam.CreateClippingRangeAttr(Gf.Vec2f(0.05, 100000.0))
    eye, tgt = Gf.Vec3d(*eye), Gf.Vec3d(*tgt)
    f = (tgt - eye).GetNormalized()
    up0 = Gf.Vec3d(0, 0, 1) if abs(Gf.Dot(f, Gf.Vec3d(0, 0, 1))) < 0.999 else Gf.Vec3d(0, 1, 0)
    r = Gf.Cross(f, up0).GetNormalized()
    u = Gf.Cross(r, f).GetNormalized()
    x = UsdGeom.Xformable(cam.GetPrim())
    x.ClearXformOpOrder()
    x.AddTransformOp().Set(Gf.Matrix4d(r[0], r[1], r[2], 0, u[0], u[1], u[2], 0,
                                       -f[0], -f[1], -f[2], 0, eye[0], eye[1], eye[2], 1))
    return cam


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, help="카메라를 넣을 씬 USD")
    ap.add_argument("--rec", default=None,
                    help="자세 기록 npz. 여기서 가장 많이 움직인 로봇을 고른다")
    ap.add_argument("--amr", type=int, default=None,
                    help="로봇을 직접 지정한다 (기록이 없거나 다른 대를 보고 싶을 때)")
    ap.add_argument("--mode", default="nose", choices=sorted(VIEWS),
                    help="nose=주행 시점 · chase=뒤 위 · top=바로 위")
    ap.add_argument("--link", default="chassis",
                    help="카메라를 매달 **강체 링크**. 루트에 달면 안 따라간다")
    ap.add_argument("--name", default="cam_onboard")
    a = ap.parse_args()

    stage = Usd.Stage.Open(a.stage)
    if not stage:
        raise SystemExit(f"★ 씬을 못 엽니다: {a.stage}")
    robots = stage.GetPrimAtPath("/World/Robots")
    if not robots:
        raise SystemExit("★ /World/Robots 가 없습니다 — 씬이 맞습니까?")
    ids = sorted(int(p.GetName().split("_")[1]) for p in robots.GetChildren()
                 if p.GetName().startswith("amr_"))
    if not ids:
        raise SystemExit("★ amr_* prim 이 없습니다")

    # --- 대상 로봇 ---
    if a.amr is not None:
        idx = a.amr
        why = "직접 지정"
    else:
        rec = a.rec
        if not rec or not os.path.exists(rec):
            raise SystemExit(
                "★ 자세 기록이 없어 '가장 많이 움직인 로봇' 을 못 고릅니다.\n"
                "  한 번 돌려서 기록을 만들거나 --amr 로 직접 주세요:\n"
                "    PIBT_RECORD=$OUT/rec_pibt12.npz bash run_record.sh")
        idx, dist = busiest(rec, len(ids))
        why = f"주행거리 최대 ({dist[idx]:.1f} m)"
        order = np.argsort(dist)[::-1]
        print("[cam] 로봇별 주행거리 [m]")
        for r in order:
            mark = " <-" if r == idx else ""
            print(f"[cam]   amr_{r:<2d} {dist[r]:7.1f}{mark}")
    if idx not in ids:
        raise SystemExit(f"★ amr_{idx} 가 씬에 없습니다. 있는 것: {ids}")

    link = stage.GetPrimAtPath(f"/World/Robots/amr_{idx}/{a.link}")
    if not link:
        raise SystemExit(
            f"★ amr_{idx} 에 '{a.link}' 링크가 없습니다.\n"
            f"  ArticulationRoot 에 달면 PhysX 가 안 옮겨 카메라가 제자리에 남습니다.\n"
            f"  강체 링크 이름을 --link 로 주세요 (iw.hub 은 chassis).")

    eye, tgt, focal = VIEWS[a.mode]
    path = f"/World/Robots/amr_{idx}/{a.link}/{a.name}"
    look_at_local(stage, path,
                  (eye[0], eye[1], eye[2] - WHEEL_R),
                  (tgt[0], tgt[1], tgt[2] - WHEEL_R), focal)
    stage.GetRootLayer().Save()

    print(f"[cam] 대상   amr_{idx}  ({why})")
    print(f"[cam] 시점   {a.mode}  눈 {eye} -> 목표 {tgt}  {focal:.0f}mm  (바닥 기준)")
    print(f"[cam] 부모   {a.link} 링크 — 로봇과 같이 움직입니다")
    print(path)                      # ★ 마지막 줄 = 카메라 경로. 셸이 이걸 받는다


if __name__ == "__main__":
    sys.exit(main())
