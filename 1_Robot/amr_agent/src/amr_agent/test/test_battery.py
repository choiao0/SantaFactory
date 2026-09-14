"""BatteryModel — 주행/정지 소모, 바닥 0, threshold, 충전 상승·상한."""
from amr_agent.battery import BatteryModel


def test_driving_drains_at_rate_and_idle_at_idle_ratio():
    b = BatteryModel(soc_pct=50.0, consumption_pct_per_s=0.02, idle_ratio=0.25)

    b.step(10.0, driving=True)
    after_drive = b.soc_pct
    b.step(10.0, driving=False)

    assert after_drive == 50.0 - 0.2
    assert b.soc_pct == after_drive - 0.05


def test_soc_floors_at_zero_and_ignores_non_positive_dt():
    b = BatteryModel(soc_pct=0.1, consumption_pct_per_s=1.0)

    b.step(5.0, driving=True)
    b.step(-1.0, driving=True)

    assert b.soc_pct == 0.0


def test_low_flag_at_threshold():
    b = BatteryModel(soc_pct=20.0, charge_threshold_pct=20.0)

    assert b.low
    b.soc_pct = 20.01
    assert not b.low


def test_charging_fills_at_charge_time_rate_and_caps_at_100():
    b = BatteryModel(soc_pct=90.0, charge_time_s=1000.0, charging=True)

    b.step(50.0, driving=False)          # +5 %
    assert b.soc_pct == 95.0
    b.step(1000.0, driving=False)
    assert b.soc_pct == 100.0


def test_from_profile_and_state_shape():
    b = BatteryModel.from_profile({"soc_init_pct": 80, "consumption_pct_per_s": 0.02, "idle_ratio": 0.25,
                                   "charge_time_s": 3600, "charge_threshold_pct": 20})

    assert b.state() == {"batteryCharge": 80.0, "charging": False}
