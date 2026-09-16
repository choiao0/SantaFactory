package com.ssafy.santafactory.service.estimate;

import org.junit.jupiter.api.Test;

import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;

class CostCalculatorTest {

    /**
     * 단가 1,500만 · 대당 구축·설치비 50만 (robots 시드 값) · 충전기 500만(미정이라 테스트 가정),
     * 충전기 1대당 AMR 4대. → 대당 비용 1,550만.
     */
    private final CostCalculator calculator = new CostCalculator(
            new EstimateProperties(15_000_000L, 5_000_000L, 500_000L, 28, 6, 4, 1, Duration.ofMinutes(30), Duration.ofHours(6), "in,in,out,out,out,out", false, Duration.ofMinutes(10), 10, 10, 6, null));

    @Test
    void chargers_round_up_one_per_four_amrs() {
        assertThat(calculator.chargers(1)).isEqualTo(1);
        assertThat(calculator.chargers(4)).isEqualTo(1);
        assertThat(calculator.chargers(5)).isEqualTo(2);
        assertThat(calculator.chargers(8)).isEqualTo(2);
    }

    @Test
    void chargers_never_exceed_the_simulation_limit_of_six() {
        assertThat(calculator.chargers(100)).isEqualTo(6);
    }

    @Test
    void cost_scales_install_fee_per_amr_not_as_a_lump_sum() {
        // 6대 = (1500만 + 50만) × 6 + 충전기 2대 1000만 = 9300만 + 1000만
        assertThat(calculator.cost(6)).isEqualTo(103_000_000L);
        // 1대는 대당 비용 + 충전기 1대
        assertThat(calculator.cost(1)).isEqualTo(20_500_000L);
    }

    @Test
    void cost_steps_up_where_another_charger_is_needed() {
        // 4→5대: AMR 1대(1550만) + 충전기 1대(500만)
        assertThat(calculator.cost(5) - calculator.cost(4)).isEqualTo(20_500_000L);
        // 5→6대: AMR 1대만 (충전기는 그대로 2대)
        assertThat(calculator.cost(6) - calculator.cost(5)).isEqualTo(15_500_000L);
    }

    @Test
    void max_amr_count_divides_the_budget_by_per_unit_cost_then_adds_margin() {
        // 1억 / 1550만 = 6대, + 여유 1 = 7대
        assertThat(calculator.maxAmrCount(100_000_000L)).isEqualTo(7);
    }

    @Test
    void the_budget_binds_before_the_charge_zone_capacity() {
        // 예산 3억(창고 시드 값) ÷ 대당 1,550만 = 19대, + 여유 1 = 20대.
        // 상한 28 은 이보다 크므로 걸리지 않는다 — 예산이 실질 상한이다.
        assertThat(calculator.maxAmrCount(300_000_000L)).isEqualTo(20);
    }

    @Test
    void max_amr_count_is_capped_at_the_charge_zone_capacity() {
        // 예산이 아주 크면 충전 존 용량(28)에서 잘린다. 그 이상은 시뮬이 배치 단계에서 죽는다
        assertThat(calculator.maxAmrCount(10_000_000_000L)).isEqualTo(28);
    }

    @Test
    void max_amr_count_tries_at_least_one_even_on_a_tiny_budget() {
        assertThat(calculator.maxAmrCount(0L)).isEqualTo(1);
    }

    @Test
    void undecided_charger_price_simply_drops_out_of_the_cost() {
        CostCalculator noChargerPrice = new CostCalculator(
                new EstimateProperties(15_000_000L, 0L, 500_000L, 28, 6, 4, 1, Duration.ofMinutes(30), Duration.ofHours(6), "in,in,out,out,out,out", false, Duration.ofMinutes(10), 10, 10, 6, null));

        assertThat(noChargerPrice.cost(6)).isEqualTo(93_000_000L);
    }

    @Test
    void undecided_prices_fall_back_to_the_fleet_cap() {
        CostCalculator undecided = new CostCalculator(
                new EstimateProperties(0L, 0L, 0L, 28, 6, 4, 1, Duration.ofMinutes(30), Duration.ofHours(6), "in,in,out,out,out,out", false, Duration.ofMinutes(10), 10, 10, 6, null));

        assertThat(undecided.maxAmrCount(1_000L)).isEqualTo(28);
        assertThat(undecided.cost(6)).isZero();
    }
}
