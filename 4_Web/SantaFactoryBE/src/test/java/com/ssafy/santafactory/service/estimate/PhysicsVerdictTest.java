package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.dto.simulation.PhysicsMetrics;
import com.ssafy.santafactory.entity.estimate.VerifyRunStatus;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/** 물리 판정 규칙 — 명세 §D (S15P21A106-244). */
class PhysicsVerdictTest {

    @Test
    void passes_when_contact_free_and_the_window_ratio_is_at_least_80_percent() {
        PhysicsMetrics physics = physics(0, 0, 0.80);

        assertThat(PhysicsVerdict.of(VerifyRunStatus.DONE, physics)).isEqualTo(PhysicsVerdict.Verdict.PASS);
    }

    @Test
    void warns_when_contact_free_but_the_window_ratio_is_below_80_percent() {
        PhysicsMetrics physics = physics(0, 0, 0.79);

        assertThat(PhysicsVerdict.of(VerifyRunStatus.DONE, physics)).isEqualTo(PhysicsVerdict.Verdict.WARN);
    }

    @Test
    void fails_when_there_is_a_robot_contact_even_if_the_ratio_is_high() {
        PhysicsMetrics physics = physics(1, 0, 0.95);

        assertThat(PhysicsVerdict.of(VerifyRunStatus.DONE, physics)).isEqualTo(PhysicsVerdict.Verdict.FAIL);
    }

    @Test
    void fails_when_there_is_a_rack_contact() {
        PhysicsMetrics physics = physics(0, 2, 0.95);

        assertThat(PhysicsVerdict.of(VerifyRunStatus.DONE, physics)).isEqualTo(PhysicsVerdict.Verdict.FAIL);
    }

    @Test
    void fails_when_the_verification_itself_failed_regardless_of_physics() {
        PhysicsMetrics physics = physics(0, 0, 0.99);

        assertThat(PhysicsVerdict.of(VerifyRunStatus.FAILED, physics)).isEqualTo(PhysicsVerdict.Verdict.FAIL);
    }

    @Test
    void is_not_applicable_when_there_is_no_physics_object() {
        assertThat(PhysicsVerdict.of(VerifyRunStatus.DONE, null)).isEqualTo(PhysicsVerdict.Verdict.NA);
    }

    /** 구간 재생이 아니면 {@code window_actions} 가 없다 — 판정할 수 없다. */
    @Test
    void is_not_applicable_when_window_actions_is_missing() {
        PhysicsMetrics physics = new PhysicsMetrics("isaac-headless", 10, null, null, null, null, null, null,
                0, 0.3, 0, 0.0, 0, 0.0, 0, 0, 0, 0, 0, 0, null, null, null, null);

        assertThat(PhysicsVerdict.of(VerifyRunStatus.DONE, physics)).isEqualTo(PhysicsVerdict.Verdict.NA);
    }

    private PhysicsMetrics physics(int robotContacts, int rackContacts, double windowRatio) {
        return new PhysicsMetrics("isaac-headless", 10, 660.0, 600.0, 60.0, 600.0, 701.3, 0.94,
                robotContacts, 0.334, rackContacts, 0.0, 284, 46.6, 0, 1, 0, 62, 3140, 3134,
                new PhysicsMetrics.Lag(2804, 40.4, 91.9, 157.6, 47.0, 0.9),
                new PhysicsMetrics.WindowActions(3365, 2804, windowRatio, 157.0),
                new PhysicsMetrics.Blocked(372_000L, 0L, 10_406L, 0L, 89_963L, 0.27),
                new PhysicsMetrics.DesWindow(162, 2970, 191, 205));
    }
}
