package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse.Verification;
import com.ssafy.santafactory.dto.estimate.VerifyNoticeCode;
import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.entity.estimate.VerifySnapshot;
import com.ssafy.santafactory.entity.simulation.RunKpiDetail;
import com.ssafy.santafactory.entity.simulation.SimScenario;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class VerifyComparatorTest {

    private final VerifyComparator comparator = new VerifyComparator(new VerifyCompareProperties(0.10, 0.01));

    @Test
    void null_snapshot_means_no_verification_block() {
        assertThat(comparator.compare(null, recommended())).isNull();
    }

    @Test
    void not_finished_when_status_is_not_done_or_reason_is_not_window_elapsed() {
        Verification failed = comparator.compare(snapshot("failed", "runner NDEATH", 14, 14, null, 152.0, 400.0, 0.07), recommended());
        Verification cutShort = comparator.compare(snapshot("done", "heartbeat lost", 14, 14, null, 152.0, 400.0, 0.07), recommended());

        assertThat(failed.notice()).isEqualTo(VerifyNoticeCode.NOT_FINISHED);
        assertThat(failed.comparison()).isNull();
        assertThat(cutShort.notice()).isEqualTo(VerifyNoticeCode.NOT_FINISHED);
    }

    @Test
    void different_conditions_hides_comparison_when_fms_warnings_present() {
        Verification v = comparator.compare(snapshot("done", "window elapsed", 14, 14, "[\"neutral theta\"]", 152.0, 400.0, 0.07), recommended());

        assertThat(v.notice()).isEqualTo(VerifyNoticeCode.DIFFERENT_CONDITIONS);
        assertThat(v.comparison()).isNull();
    }

    @Test
    void no_baseline_when_recommended_run_or_its_detail_is_missing() {
        VerifySnapshot ok = snapshot("done", "window elapsed", 14, 14, null, 152.0, 400.0, 0.07);
        SimScenario withoutDetail = SimScenario.queued(estimate(), "est_1_n14", 14, 0L);
        withoutDetail.markDone(95.6, 70.2, 956L, 384.0);

        assertThat(comparator.compare(ok, null).notice()).isEqualTo(VerifyNoticeCode.NO_BASELINE);
        assertThat(comparator.compare(ok, withoutDetail).notice()).isEqualTo(VerifyNoticeCode.NO_BASELINE);
        assertThat(comparator.compare(snapshot("done", "window elapsed", 14, 14, null, null, null, null), recommended()).notice())
                .isEqualTo(VerifyNoticeCode.NO_BASELINE);
    }

    @Test
    void partial_fleet_when_robots_online_below_n_robots_but_comparison_shown() {
        Verification v = comparator.compare(snapshot("done", "window elapsed", 14, 12, null, 152.0, 390.0, 0.07), recommended());

        assertThat(v.notice()).isEqualTo(VerifyNoticeCode.PARTIAL_FLEET);
        assertThat(v.comparison()).isNotNull();
        assertThat(v.robotsOnline()).isEqualTo(12);
    }

    @Test
    void slower_at_peak_when_lead_time_p90_exceeds_tolerance() {
        Verification v = comparator.compare(snapshot("done", "window elapsed", 14, 14, null, 159.0, 430.0, 0.068), recommended());

        assertThat(v.notice()).isEqualTo(VerifyNoticeCode.SLOWER_AT_PEAK);
        assertThat(v.comparison().leadTimeP90S().diff()).isEqualTo(46.0);
    }

    @Test
    void slower_at_peak_when_conflict_wait_exceeds_tolerance() {
        Verification v = comparator.compare(snapshot("done", "window elapsed", 14, 14, null, 159.0, 384.0, 0.081), recommended());

        assertThat(v.notice()).isEqualTo(VerifyNoticeCode.SLOWER_AT_PEAK);
        assertThat(v.comparison().conflictWaitRatio().diff()).isCloseTo(0.013, within(1e-9));
    }

    @Test
    void matches_when_both_within_tolerance() {
        Verification v = comparator.compare(snapshot("done", "window elapsed", 14, 14, null, 152.0, 414.0, 0.075), recommended());

        assertThat(v.notice()).isEqualTo(VerifyNoticeCode.MATCHES);
        assertThat(v.comparison().throughputOrdersPerH().diff()).isEqualTo(-7.0);
        assertThat(v.comparison().leadTimeP90S().diff()).isEqualTo(30.0);
    }

    @Test
    void a_missing_metric_leaves_only_that_metric_empty() {
        Verification v = comparator.compare(snapshot("done", "window elapsed", 14, 14, null, 152.0, null, 0.07), recommended());

        assertThat(v.notice()).isEqualTo(VerifyNoticeCode.MATCHES);
        assertThat(v.comparison().leadTimeP90S().verified()).isNull();
        assertThat(v.comparison().leadTimeP90S().diff()).isNull();
        assertThat(v.comparison().throughputOrdersPerH().diff()).isEqualTo(-7.0);
    }

    @Test
    void an_old_payload_without_reason_counts_as_finished() {
        Verification v = comparator.compare(snapshot("done", null, null, null, null, 159.0, 384.0, 0.068), recommended());

        assertThat(v.notice()).isEqualTo(VerifyNoticeCode.MATCHES);
    }

    private static Estimate estimate() {
        return Estimate.open(null, "iw.hub", 95.0, 60.0, 300_000_000L);
    }

    /** 권장 14대 run — 시간당 159건, p90 384초, 혼잡 6.8 %. */
    private static SimScenario recommended() {
        SimScenario run = SimScenario.queued(estimate(), "est_1_n14", 14, 217_000_000L);
        run.markDone(95.6, 70.2, 956L, 384.0);
        run.applyKpiDetail(new RunKpiDetail(1000, 956, 212.0, 48.0, 159.0, 0.068, 171_400L));
        return run;
    }

    private static VerifySnapshot snapshot(String status, String reason, Integer nRobots, Integer online, String warnings,
                                           Double throughputPerH, Double p90, Double conflict) {
        return new VerifySnapshot("verify_1", status, reason, null, nRobots, online, 600, warnings,
                throughputPerH, p90, conflict, LocalDateTime.now());
    }
}
