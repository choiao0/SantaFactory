# -*- coding: utf-8 -*-
"""경로 계획기 레지스트리.

`amr/main.py` 는 이름만 보고 계획기를 고른다. 새 계획기를 붙이려면
이 폴더에 모듈 하나를 추가하면 끝이고, main.py 는 손대지 않는다.

계획기 모듈이 갖춰야 하는 것 (전부 모듈 최상위):

    NAME    str   CLI 에서 쓰는 이름
    DESC    str   한 줄 설명
    DRIVE   str   실행 방식 — "time" 또는 "adg"
                    time : 궤적 JSON 의 **시각**을 추종 (amr_driver_v2)
                    adg  : ADG 의 **순서**를 따름 (isaac_drive)
    OUT     str   산출물 폴더 (저장소 루트 기준)
    plan(n, seed=None, seconds=None, map_dir=None, extra=None) -> dict
                  계획해서 OUT 에 쓰고 요약 dict 반환
    verify(n, map_dir=None) -> bool          (없으면 main 이 건너뛴다)
    scene_cmd(n) -> list[str]                씬 빌드 명령 (서버에서 실행)
    run_cmd(n) -> list[str]                  주행 명령 (서버에서 실행)

**계획기 본체를 여기로 옮기지 않는다.** 어댑터는 기존 CLI 를 그대로 부른다.
검증된 파이프라인을 건드리지 않으면서 진입점만 하나로 모으는 것이 목적이다.
"""
import importlib
import os
import pkgutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # t3_amr/
MAKE_PATH = os.path.join(ROOT, "amr", "make_path")

_REG = None


def registry():
    """{이름: 모듈}. 이 폴더의 밑줄 아닌 모듈을 전부 읽는다."""
    global _REG
    if _REG is None:
        _REG = {}
        for m in pkgutil.iter_modules([HERE]):
            if m.name.startswith("_"):
                continue
            mod = importlib.import_module(f"{__name__}.{m.name}")
            name = getattr(mod, "NAME", m.name)
            _REG[name] = mod
    return _REG


def get(name):
    reg = registry()
    if name not in reg:
        raise SystemExit(f"모르는 계획기: {name}\n  가능한 것: {', '.join(sorted(reg))}")
    return reg[name]


def default_map():
    """기본 맵 = `t3_amr/warehouse/map`. **이것이 단일 소스다.**

    1061×1151 · 0.1 m/셀. pitch 1.2 로 풀링하면 격자 88×95 · 통행칸 5,889 ·
    스테이션 성분 1,298 이 나와야 맞는다 (이관 검증 기준값).

        occupancy_grid.npy  sha256 563e6aeb…
        stations.json       sha256 f8edcf71…   ← `handoff` 가 들어 있다

    ★ `t3_warehouse_map/map` 을 쓰지 않는다. 팀 기본 맵(v6.0)은 격자가
      **다르고**(sha 3f9548db…) `stations.json` 에 `handoff` 가 없다.
      `handoff` 는 `GOAL_CATS` 다섯 중 하나라, 그 맵으로 계획하면 목표
      카테고리가 조용히 하나 빠진다. 씬을 v6.0 격자로 다시 지은 뒤에
      단일 소스를 그쪽으로 옮긴다.

    ★ 판정은 `occupancy_grid.npy` 로 한다. `obstacle_mask.npy` 로 보면
      격자가 없는 폴더(map_fms 계열)까지 "맵 있음"으로 통과한다.
    """
    env = os.environ.get("MAP", "")
    cands = [env] if env else []
    cands += [os.path.join(ROOT, "warehouse", "map")]
    for d in cands:
        if d and os.path.isfile(os.path.join(d, "occupancy_grid.npy")):
            return os.path.abspath(d)
    raise SystemExit(
        "★ 맵을 찾을 수 없습니다 (occupancy_grid.npy 기준).\n"
        "  $MAP 을 지정하거나 2_Simulation/t3_amr/warehouse/map/ 을 확인하세요.\n"
        "  (source 2_Simulation/t3_amr/paths.sh 가 $MAP 을 잡아줍니다)")
