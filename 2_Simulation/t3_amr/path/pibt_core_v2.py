# -*- coding: utf-8 -*-
"""PIBT 코어 **로더** — `3_FMS/sim_engine/pibt_core.py` **원본**을 직접 쓴다.

한때 이 파일은 그 원본의 바이트 동일 사본이었다. 사본은 상류가 바뀌면 조용히
갈린다 — 실제로 갈렸다. 2026-09-07 에 FMS 가 `pibt_core.py` 를 `pibt/`
패키지(geometry·cell·hgraph·liveness·heading)로 분해하고 파사드만 남겼는데
(`8e7ab7d`, 결과 비트 동일), 우리 사본은 분해 전 판이라 그 뒤의 개선이 하나도
안 들어왔다. 특히

    befb87d  헤딩 거리장 HGraph 정적 테이블 + 재계획 증분 복구
             28대 57~86 s -> 7~11 s (결과 비트 동일)

**같은 저장소로 들어오면서 사본이 필요 없어졌다** (S15P21A106-141). 원본이
`../../3_FMS/sim_engine` 에 있으므로 그것을 로드한다. 사본이 갈릴 여지가
구조적으로 사라진다 — 이관의 가장 큰 이득이다.

찾는 순서
---------
    1. $PIBT_CORE_DIR                    명시 지정 (sim_engine 폴더)
    2. <저장소>/3_FMS/sim_engine         기본. **같은 커밋의 원본**
    3. path/_pibt_core_vendor.py         벤더 사본 (마지막 수단)

2번이 기본이다. 1번은 사람이 일부러 준 값이므로 환경 사고가 아니고, 쓰이면
stderr 에 찍히므로 로그만 봐도 무엇으로 돌았는지 안다.

3번으로 떨어지면 **경고를 찍는다.** 조용한 후퇴가 하루를 날린 적이 있다
(2026-09-07, occupancy_grid 후퇴 분기). 벤더 사본은 2026-09-07 이전 판이라
28대 계획이 8배 느리다.

왜 sys.path 조작이 필요한가
---------------------------
파사드가 `from pibt.geometry import *` 를 하므로 `pibt/` 패키지가 import
가능해야 한다. 그 부모(=`sim_engine`)를 `sys.path` 에 넣어야 한다.
`sim_engine/*` 는 전부 flat import 라 이 방식 말고는 방법이 없다.

이름
----
파일명이 `_v2` 인 것은 `isaac_drive.py` 가 `from pibt_core import ...` 로
부르기 때문이다. 이 모듈은 로드 후 **자기 자신을 그 모듈로 치환**하므로
`pibt_core` 와 `pibt_core_v2` 가 같은 객체다.

    import pibt_core_v2 as pc
    pc is sys.modules["pibt_core"]      # True

★ 그렇다고 **여기에 대입하면 안쪽까지 바뀌는 것은 아니다** (2026-09-15 정정).
  예전 주석은 "`REVERSE_FACTOR` 같은 모듈 변수 대입이 서로에게 보인다" 고
  적어 두었는데 사실이 아니다. 파사드는 `from pibt.geometry import *` 로
  **값을 복사**하고, `pibt/heading.py` · `pibt/hgraph.py` 도 각각
  `from .geometry import REVERSE_FACTOR` 로 제 이름공간에 복사본을 갖는다.
  그래서 파사드에만 넣으면 정작 읽는 쪽이 옛 값을 본다:

      pc.REVERSE_FACTOR = 1.0
      pibt_core        = 1.0    <- 바뀐 것처럼 보이고
      pibt.geometry    = 3.0
      pibt.heading     = 3.0    <- candidates_h 가 실제로 읽는 곳
      pibt.hgraph      = 3.0    <- 거리장이 읽는 곳

  상수를 흔들어 보려면 **네 곳을 다 세팅**해야 한다. `MOVE_TICKS` 처럼
  `from ... import` 로 퍼진 다른 상수도 같다. 실험용 헬퍼는
  `tools/reverse_sweep.py` 의 `set_const()` 를 쓸 것.
"""
import importlib.util
import os
import sys

# ★ 상류 의존성 주의 (2026-09-16).
#   `3_FMS/sim_engine/pibt/hgraph.py` 가 `from numba import njit` 을 모듈
#   최상단에서 한다 (FMS -225, 재계획 거리장 3.1배 가속). 이 파사드는 그
#   파일을 **직접 로드**하므로 numba 가 없으면 `ModuleNotFoundError` 로
#   터진다 — Isaac 이 필요 없는 계획 층 도구까지 전부.
#
#   사본을 안 두고 원본을 로드하는 구조의 대가다. 상류가 의존성을 늘리면
#   우리 환경도 같이 늘려야 한다. `install.sh` 의 import 확인에 넣어 뒀다.

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

# 기본은 **같은 저장소의 원본**이다 (`2_Simulation/t3_amr/path` -> `3_FMS/sim_engine`).
# 사본을 두지 않으므로 갈릴 여지가 없다.
#
# `PIBT_CORE_DIR` 만 이것을 이긴다. 사람이 **일부러** 준 값이므로 환경 사고가
# 아니고, 쓰이면 stderr 에 찍히므로 로그만 봐도 무엇으로 돌았는지 안다.
_REPO = os.path.join(_ROOT, "..", "..", "3_FMS", "sim_engine")
_ENV = os.environ.get("PIBT_CORE_DIR", "")
CANDIDATES = [(_ENV, "env"), (_REPO, "repo")]


def _find_upstream():
    """(`pibt_core.py` 가 있는 sim_engine 폴더, 출처표시). 없으면 (None, None)."""
    for d, kind in CANDIDATES:
        if not d:
            continue
        d = os.path.abspath(os.path.expanduser(d))
        if os.path.isfile(os.path.join(d, "pibt_core.py")):
            return d, kind
    return None, None


def _load(path, name, extra_syspath=None):
    if extra_syspath and extra_syspath not in sys.path:
        sys.path.insert(0, extra_syspath)      # 파사드의 `from pibt.x import *` 용
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                    # 순환 import 대비, exec 전에 등록
    spec.loader.exec_module(mod)
    return mod


_up, _kind = _find_upstream()
if _up:
    _core = _load(os.path.join(_up, "pibt_core.py"), "pibt_core", _up)
    _core.__pibt_source__ = os.path.join(_up, "pibt_core.py")
    _core.__pibt_vendored__ = False
    if _kind == "env":
        # 저장소 밖이다. 커밋에 안 남으므로 **무엇으로 돌았는지 반드시 남긴다.**
        sys.stderr.write(
            "[pibt_core_v2] ★ PIBT_CORE_DIR 로 저장소 **밖**을 씁니다: %s\n"
            "   이 코드는 이 저장소의 커밋에 없습니다 — 결과를 기록할 때 같이 적으세요.\n"
            % _core.__pibt_source__)
else:
    sys.stderr.write(
        "\n[pibt_core_v2] ★★ 3_FMS/sim_engine 을 못 찾아 **벤더 사본**으로 후퇴합니다.\n"
        "   찾아본 곳: %s\n"
        "   사본은 2026-09-07 이전 판이라 그 뒤의 개선(HGraph 정적 테이블 등)이\n"
        "   빠져 있습니다. 28대 계획이 8배 느립니다. 붙이려면:\n"
        "     3_FMS/sim_engine/ 이 같은 저장소에 있어야 하거나\n"
        "     PIBT_CORE_DIR=<...>/3_FMS/sim_engine  로 지정하세요.\n\n"
        % ", ".join(os.path.abspath(os.path.expanduser(d))
                    for d, _ in CANDIDATES if d))
    _core = _load(os.path.join(_HERE, "_pibt_core_vendor.py"), "pibt_core")
    _core.__pibt_source__ = os.path.join(_HERE, "_pibt_core_vendor.py")
    _core.__pibt_vendored__ = True

def set_const(name, value):
    """상수 하나를 **복사본을 가진 모든 모듈**에 세팅한다. 바꾼 모듈 이름을 낸다.

    왜 필요한가: 위 ★ 에 적은 대로 `from ... import` 가 값을 복사해 가므로
    한 곳에 대입해서는 정작 읽는 쪽이 안 바뀐다. 실험할 때 이걸 쓴다.

        set_const("REVERSE_FACTOR", 1.0)
        -> ['pibt.geometry', 'pibt.heading', 'pibt.hgraph', 'pibt_core']

    ★ 거리장 캐시가 있으면 먼저 비워야 한다. 비용을 바꿔도 이미 계산된
      `dist` 를 재사용하면 옛 비용으로 짠 경로가 그대로 나온다.
    """
    hit = []
    for mod_name, mod in list(sys.modules.items()):
        d = getattr(mod, "__dict__", None)
        if d is not None and name in d:
            d[name] = value
            hit.append(mod_name)
    if not hit:
        raise KeyError(f"{name} 을 가진 모듈이 없다 — 코어가 로드되기 전인가")
    return sorted(hit)


# --- 실험용 상수 오버라이드 (기본 꺼짐) -----------------------------------
#   `geometry.py` 는 FMS 소스라 우리가 못 고친다. 그런데 계획을 돌리는 것은
#   `pibt_scene.py` 라는 **별도 프로세스**라 in-process 몽키패치가 안 닿는다.
#   그래서 환경변수를 로더가 읽어 준다 — 프로세스 경계를 넘는 유일한 통로다.
#
#   ★ 환경변수를 안 주면 **한 줄도 실행되지 않는다.** FMS 와 비트 동일이
#     기본이고, `adg_fingerprint` 가 지키는 것이 바로 그 동일성이다.
#     여기서 기본값을 바꾸면 두 트랙의 경로가 조용히 갈린다.
#   ★ 마지막 줄이 이 모듈을 `_core` 로 치환하므로, 헬퍼는 `_core` 에 붙여야
#     `import pibt_core_v2 as pc; pc.set_const(...)` 가 된다.
_core.set_const = set_const

_OVERRIDABLE = {"PIBT_REVERSE_FACTOR": ("REVERSE_FACTOR", float)}
for _env, (_const, _cast) in _OVERRIDABLE.items():
    _raw = os.environ.get(_env, "").strip()
    if not _raw:
        continue
    _val = _cast(_raw)
    _where = set_const(_const, _val)
    sys.stderr.write(
        "[pibt_core_v2] ★ %s=%s 로 %s 를 덮어썼습니다 (%s).\n"
        "   FMS 기본값이 아닙니다 — 결과를 기록할 때 반드시 같이 적으세요.\n"
        % (_env, _raw, _const, ", ".join(_where)))

# `import pibt_core_v2` 도 같은 모듈 객체를 받게 한다. 이 줄이 마지막이어야 한다.
sys.modules[__name__] = _core
