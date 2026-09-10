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
    """기본 맵. `$MAP` 이 있으면 그것, 없으면 `2_Simulation/t3_warehouse_map/map`.

    맵은 `t3_warehouse_map/` 이 **단일 소스**다 — `scene_builder` 도, ROS SIL
    스택(`sil_ros/gridmap.py`)도, Nav2 위치추정(`t3_warehouse/ros2/loc.launch.py`)
    도 같은 폴더를 본다. 그래서 여기서 사본을 들고 있지 않는다.

    ★ 계획 좌표를 3_FMS 와 맞추려면 `map_fms` 를 써야 한다. 두 맵은 `aisle_buf`
      남쪽 줄이 y 46.0 vs 46.2, 작업 라인이 y 33.8 vs 40.4 로 다르고, 그 0.2 m
      때문에 랙→버퍼 매핑(`3_FMS/map/build_rack_map.py`)이 성립하지 않는다.
      `paths.sh` 가 `$MAP_FMS` 를 잡아 두므로 이렇게 쓴다.

          MAP=$MAP_FMS python amr/main.py plan --planner pibt_h

      기본값을 map_fms 로 두지 않는 이유는, 그 맵으로 계획하고 **현행 씬**에서
      주행하면 로봇이 작업대가 없는 빈 바닥으로 가기 때문이다. 씬을 그 격자로
      다시 지은 뒤에 기본값을 옮긴다.
    """
    env = os.environ.get("MAP", "")
    cands = [env] if env else []
    cands += [os.path.join(ROOT, "..", "t3_warehouse_map", "map")]
    for d in cands:
        if d and os.path.isfile(os.path.join(d, "occupancy_grid.npy")):
            return os.path.abspath(d)
    raise SystemExit(
        "★ 맵을 찾을 수 없습니다.\n"
        "  $MAP 을 지정하거나 2_Simulation/t3_warehouse_map/map/ 을 확인하세요.\n"
        "  (source 2_Simulation/t3_amr/paths.sh 가 $MAP·$MAP_FMS 를 잡아줍니다)")
