package com.ssafy.santafactory.service.estimate;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class CostCalculatorTest {

    /** 대당 1억 · 충전기 500만 · 설치 3천만, 충전기 1대당 AMR 4대. */
    private final CostCalculator calculator = new CostCalculator(
            new EstimateProperties(100_000_000L, 5_000_000L, 30_000_000L, 8, 6, 4, 1));

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
    void cost_sums_amrs_chargers_and_installation() {
        // 6대 = 6억 + 충전기 2대 1천만 + 설치 3천만
        assertThat(calculator.cost(6)).isEqualTo(640_000_000L);
    }

    @Test
    void max_fleet_divides_the_budget_after_installation_then_adds_margin() {
        // (5.3억 - 3천만) / 1억 = 5대, + 여유 1 = 6대
        assertThat(calculator.maxFleet(530_000_000L)).isEqualTo(6);
    }

    @Test
    void max_fleet_is_capped_at_eight() {
        assertThat(calculator.maxFleet(100_000_000_000L)).isEqualTo(8);
    }

    @Test
    void max_fleet_tries_at_least_one_even_on_a_tiny_budget() {
        assertThat(calculator.maxFleet(0L)).isEqualTo(1);
    }

    @Test
    void undecided_prices_fall_back_to_the_fleet_cap() {
        CostCalculator undecided = new CostCalculator(
                new EstimateProperties(0L, 0L, 0L, 8, 6, 4, 1));

        assertThat(undecided.maxFleet(1_000L)).isEqualTo(8);
        assertThat(undecided.cost(6)).isZero();
    }
}
