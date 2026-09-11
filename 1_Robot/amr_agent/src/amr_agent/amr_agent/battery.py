"""배터리 SoC 모델 (순수 파이썬). 값은 프로파일 battery 절에서 온다 — BE 의 battery · consumption · charge_time · charge_threshold.

주행 중 consumption_pct_per_s 로 줄고, 정지 중엔 idle_ratio 배(sim_engine 규약: 정지 소모 = 주행의 1/4), 충전 중엔
100 % 를 charge_time_s 에 채우는 속도로 오른다. 에이전트는 SoC 를 VDA state.batteryState 로 내고 threshold 아래면
information 에 batteryLow 를 싣는다 — 충전 결정 자체는 FMS 몫이다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BatteryModel:
    soc_pct: float = 100.0
    consumption_pct_per_s: float = 0.0
    idle_ratio: float = 0.25
    charge_time_s: float = 3600.0
    charge_threshold_pct: float = 20.0
    charging: bool = False

    @classmethod
    def from_profile(cls, battery: dict) -> "BatteryModel":
        return cls(float(battery["soc_init_pct"]), float(battery["consumption_pct_per_s"]),
                   float(battery["idle_ratio"]), float(battery["charge_time_s"]),
                   float(battery["charge_threshold_pct"]))

    def step(self, dt: float, driving: bool) -> float:
        """dt 초 진행. 새 SoC 를 돌려주고 내부 상태도 그 값이 된다."""
        if dt <= 0:
            return self.soc_pct
        if self.charging:
            soc = self.soc_pct + 100.0 / self.charge_time_s * dt
        else:
            soc = self.soc_pct - self.consumption_pct_per_s * (1.0 if driving else self.idle_ratio) * dt
        self.soc_pct = min(100.0, max(0.0, soc))
        return self.soc_pct

    @property
    def low(self) -> bool:
        return self.soc_pct <= self.charge_threshold_pct

    def state(self) -> dict:
        """VDA 5050 state.batteryState."""
        return {"batteryCharge": round(self.soc_pct, 2), "charging": self.charging}
