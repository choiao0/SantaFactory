package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse.Verification;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse.Verification.Comparison;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse.Verification.Metric;
import com.ssafy.santafactory.dto.estimate.VerifyNoticeCode;
import com.ssafy.santafactory.entity.estimate.VerifySnapshot;
import com.ssafy.santafactory.entity.simulation.RunKpiDetail;
import com.ssafy.santafactory.entity.simulation.SimScenario;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * 물리 검증 결과를 권장 대수의 계산 결과와 견준다 (S15P21A106-236).
 *
 * <p>저장하지 않고 조회할 때마다 계산한다 — 기준값을 yml 로 바꾸면 과거 견적도 새 기준으로 보인다.
 * 검증은 주문이 가장 몰리는 10분 창만 돌리므로 하루 기준인 처리율 % 는 견주지 않고,
 * 시간당 처리 주문 · 주문 처리 시간(p90) · 통로 혼잡 셋만 본다.
 */
@Component
@RequiredArgsConstructor
@EnableConfigurationProperties(VerifyCompareProperties.class)
public class VerifyComparator {

    private final VerifyCompareProperties props;

    /**
     * @param verify      견적에 남은 검증 결과. null 이면 결과도 null
     * @param recommended 권장 대수의 run. 권장이 없으면 null
     */
    public Verification compare(VerifySnapshot verify, SimScenario recommended) {
        if (verify == null) {
            return null;
        }
        if (!verify.finishedNormally()) {
            return of(verify, VerifyNoticeCode.NOT_FINISHED, null);
        }
        if (verify.ranUnderDifferentConditions()) {
            return of(verify, VerifyNoticeCode.DIFFERENT_CONDITIONS, null);
        }
        RunKpiDetail expected = recommended == null ? null : recommended.getKpiDetail();
        if (expected == null || !verify.hasKpi()) {
            return of(verify, VerifyNoticeCode.NO_BASELINE, null);
        }

        Metric throughput = metric(expected.getThroughputOrdersPerH(), verify.getThroughputOrdersPerH());
        Metric leadTime = metric(recommended.getLeadTimeP90(), verify.getLeadTimeP90S());
        Metric conflict = metric(expected.getConflictWaitRatio(), verify.getConflictWaitRatio());
        Comparison comparison = new Comparison(throughput, leadTime, conflict);

        if (verify.fleetPartiallyOnline()) {
            return of(verify, VerifyNoticeCode.PARTIAL_FLEET, comparison);
        }
        if (slowerAtPeak(leadTime, conflict)) {
            return of(verify, VerifyNoticeCode.SLOWER_AT_PEAK, comparison);
        }
        return of(verify, VerifyNoticeCode.MATCHES, comparison);
    }

    private boolean slowerAtPeak(Metric leadTime, Metric conflict) {
        boolean leadTimeWorse = leadTime.diff() != null && leadTime.expected() > 0
                && leadTime.diff() / leadTime.expected() >= props.leadTimeP90Tolerance();
        boolean conflictWorse = conflict.diff() != null && conflict.diff() >= props.conflictWaitTolerance();
        return leadTimeWorse || conflictWorse;
    }

    private static Metric metric(Double expected, Double verified) {
        Double diff = expected == null || verified == null ? null : verified - expected;
        return new Metric(expected, verified, diff);
    }

    private static Verification of(VerifySnapshot v, VerifyNoticeCode notice, Comparison comparison) {
        return new Verification(v.getStatus(), notice, v.getNRobots(), v.getRobotsOnline(), v.getWindowS(),
                v.getError(), v.getVerifiedAt(), comparison);
    }
}
