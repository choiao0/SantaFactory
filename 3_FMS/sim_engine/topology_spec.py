# -*- coding: utf-8 -*-
# ============================================================
# 토폴로지 스펙 — 맵 세트가 자기 통로·밴드·교차로 좌표를 들고 다닌다 (S15P21A106-139)
#
# 왜 필요한가. from_theta.extract_topology 와 map_loader 의 통로차단이 wallA 좌표 상수에
# 묶여 있어 다른 창고에서 못 쓴다. 규칙 기반 자동 추출은 실제로 짜 봤다가 이 맵에서 깨졌다
# (세로 통로 50개·순환로 0개, ai_theta/data/README.md '설계 결정'). 임계값 문제가 아니라
# 규칙을 더 설계해야 하는 문제다.
#
# 합성 창고 생성기(map/synth_warehouse.py)는 그 문제를 **피해 간다** — 레이아웃을 만들면서
# 통로·밴드·교차로를 이미 알고 있으므로, 추출하지 말고 그때 쓴 좌표를 topology.json 으로
# 같이 내보내면 된다. 맵 세트에 topology.json 이 있으면 그것을, 없으면 wallA 상수를 쓴다.
# 따라서 공식 맵(3_FMS/map, topology.json 없음)의 동작은 이 파일 도입 전과 비트 동일하다.
#
# 좌표 규약은 map_loader 의 1 m 격자와 동일 — 행 r, 열 c 는 다운샘플 후 격자 인덱스이고
# 구간은 전부 [시작, 끝) 반열림이다.
# ============================================================
import json
import os

# ------------------------------------------------------------
# wallA 실측 상수 (from_theta 설계 §2, 2026-09-01 실측 → 2026-09-03 맵 동기화 재산출)
# 통로 중심 열은 원래 VA_XS_M = [35.1 + 6k] 를 int((x + OFFSET_M) / CELL_M) 로 접은 값이다.
# 여기서는 접은 결과(정수 열)를 직접 적는다 — 같은 값임은 tests 가 확인한다.
# ------------------------------------------------------------
_WALL_A = dict(
    va_rows=(47, 68),                     # 세로 통로 행 [47, 68) — 랙 내부
    va_centers=tuple(range(35, 96, 6)),   # 통로 중심 열 11개, 서쪽부터
    va_half_width=1,                      # 통로 폭 = 2*half + 1 = 3
    band_s_rows=(40, 47),                 # 남쪽 가로 간선
    band_n_rows=(68, 74),                 # 북쪽 가로 간선
    band_w_cols=(20, 32),                 # 서쪽 연결 통로
    band_e_cols=(99, 109),                # 동쪽 연결 통로 — 충전 존(c103~108)이 이 안
    junction_rows=(46, 68),               # 통로가 간선에 접속하는 목 (랙 바로 바깥 행)
    home_prefixes=("charger", "charge_q"),  # 홈은 작업자리가 아님 → station 규칙 미적용
)

SPEC_FILE = "topology.json"
SCHEMA = "topology_spec/v1"

_PAIR_KEYS = ("va_rows", "band_s_rows", "band_n_rows", "band_w_cols", "band_e_cols",
              "junction_rows")
_SEQ_KEYS = ("va_centers", "home_prefixes")


class TopologySpec:
    """from_theta·map_loader 가 소비하는 창고 골격. 값은 1 m 격자 좌표."""

    __slots__ = _PAIR_KEYS + _SEQ_KEYS + ("va_half_width",)

    def __init__(self, va_rows, va_centers, va_half_width, band_s_rows, band_n_rows,
                 band_w_cols, band_e_cols, junction_rows,
                 home_prefixes=("charger", "charge_q")):
        self.va_rows = tuple(int(v) for v in va_rows)
        self.va_centers = tuple(int(v) for v in va_centers)
        self.va_half_width = int(va_half_width)
        self.band_s_rows = tuple(int(v) for v in band_s_rows)
        self.band_n_rows = tuple(int(v) for v in band_n_rows)
        self.band_w_cols = tuple(int(v) for v in band_w_cols)
        self.band_e_cols = tuple(int(v) for v in band_e_cols)
        self.junction_rows = tuple(int(v) for v in junction_rows)
        self.home_prefixes = tuple(home_prefixes)
        self._validate()

    def _validate(self):
        for k in _PAIR_KEYS:
            lo, hi = getattr(self, k)
            assert 0 <= lo < hi, f"{k} 는 0 <= 시작 < 끝 이어야 한다: {(lo, hi)}"
        assert self.va_centers, "va_centers 가 비었다"
        assert list(self.va_centers) == sorted(self.va_centers), "va_centers 는 서쪽부터 오름차순"
        assert self.va_half_width >= 0, "va_half_width 는 0 이상"
        assert self.band_s_rows[1] <= self.va_rows[0], "남 밴드는 랙 구간 아래"
        assert self.va_rows[1] <= self.band_n_rows[0], "북 밴드는 랙 구간 위"
        assert self.band_w_cols[1] <= self.va_centers[0] - self.va_half_width, "서 밴드는 랙 블록 왼쪽"
        assert self.band_e_cols[0] >= self.va_centers[-1] + self.va_half_width + 1, "동 밴드는 랙 블록 오른쪽"

    # -- 파생 --------------------------------------------------
    @property
    def ring_rows(self):
        """순환로가 도는 행 구간 [남 밴드 시작, 북 밴드 끝)."""
        return (self.band_s_rows[0], self.band_n_rows[1])

    @property
    def ring_cols(self):
        return (self.band_w_cols[0], self.band_e_cols[1])

    @property
    def n_aisles(self):
        return len(self.va_centers)

    def aisle_cols(self, center):
        """통로 중심 열 → 통로가 차지하는 열 구간 [c0, c1)."""
        return (center - self.va_half_width, center + self.va_half_width + 1)

    # -- 직렬화 ------------------------------------------------
    def to_dict(self):
        d = {"schema": SCHEMA}
        d.update({k: list(getattr(self, k)) for k in _PAIR_KEYS})
        d["va_centers"] = list(self.va_centers)
        d["va_half_width"] = self.va_half_width
        d["home_prefixes"] = list(self.home_prefixes)
        return d

    @classmethod
    def from_dict(cls, d):
        schema = d.get("schema", SCHEMA)
        assert schema == SCHEMA, f"모르는 topology 스키마: {schema}"
        kw = {k: d[k] for k in _PAIR_KEYS}
        kw["va_centers"] = d["va_centers"]
        kw["va_half_width"] = d["va_half_width"]
        if "home_prefixes" in d:
            kw["home_prefixes"] = d["home_prefixes"]
        return cls(**kw)

    def save(self, map_dir):
        path = os.path.join(map_dir, SPEC_FILE)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)
        return path

    def __eq__(self, other):
        return isinstance(other, TopologySpec) and self.to_dict() == other.to_dict()

    def __repr__(self):
        return (f"TopologySpec(통로 {self.n_aisles}개 중심 {self.va_centers[0]}~{self.va_centers[-1]}, "
                f"행 {self.va_rows}, 링 {self.ring_rows}×{self.ring_cols})")


WALL_A = TopologySpec(**_WALL_A)


def load_spec(map_dir):
    """`<map_dir>/topology.json` 이 있으면 그 스펙, 없으면 wallA 상수.

    공식 맵(3_FMS/map)에는 이 파일이 없다 — wallA 좌표가 곧 정답이라 굳이 두지 않았다.
    합성 창고는 생성기가 반드시 같이 쓴다 (map/synth_warehouse.py).
    """
    if map_dir is None:
        return WALL_A
    path = os.path.join(map_dir, SPEC_FILE)
    if not os.path.exists(path):
        return WALL_A
    with open(path, encoding="utf-8") as f:
        return TopologySpec.from_dict(json.load(f))
