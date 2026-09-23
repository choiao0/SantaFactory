package com.ssafy.santafactory.service.estimate.quote;

import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse.Run;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse.RunKpi;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse.Verification;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse.Verification.Comparison;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse.Verification.Metric;
import com.ssafy.santafactory.dto.estimate.VerifyNoticeCode;
import com.ssafy.santafactory.dto.warehouse.WarehouseResponse;
import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.entity.estimate.RunStatus;
import com.ssafy.santafactory.service.estimate.EstimateProperties;

import java.time.Duration;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;

/** 구성안 샘플 시나리오 — 판교 3PL 센터 B동, 1~28대, 권장 14대, 효과 정체 15대. */
final class QuoteFixtures {

    static final double[] THR = {12.3, 23.4, 32.0, 38.9, 47.5, 55.1, 62.0, 68.4, 75.2, 81.5, 86.9, 90.6, 93.2, 95.6,
            97.9, 98.3, 98.4, 98.5, 98.6, 98.6, 98.6, 98.6, 98.6, 98.6, 98.6, 98.6, 98.6, 98.6};
    static final double[] UTL = {98.1, 97.4, 96.3, 95.0, 93.6, 92.0, 90.1, 88.0, 85.3, 82.3, 79.4, 76.4, 73.1, 70.2,
            66.9, 64.0, 61.4, 59.1, 57.0, 55.0, 53.3, 51.7, 50.2, 48.9, 47.8, 46.8, 46.0, 45.2};
    static final double[] P90 = {4820, 3980, 3210, 2410, 1990, 1640, 1400, 1210, 960, 760, 620, 512, 448, 384,
            351, 322, 308, 296, 291, 288, 284, 280, 276, 272, 269, 266, 263, 261};
    static final long UNIT = 15_500_000L;
    static final long BUDGET = 300_000_000L;

    static final EstimateProperties PROPS = new EstimateProperties(15_000_000L, 0L, 500_000L, 28, 6, 4, 1,
            Duration.ofMinutes(30), Duration.ofHours(6), "out", false, Duration.ofMinutes(10), Duration.ofMinutes(25), 10, 10, 6, null);
    static final QuotePdfProperties PDF = new QuotePdfProperties("", Duration.ofSeconds(30), "https://santafactory.app");

    private QuoteFixtures() {
    }

    static Run run(long estimateId, int n) {
        double thr = THR[n - 1], utl = UTL[n - 1];
        return new Run("est_%d_n%d".formatted(estimateId, n), n, RunStatus.DONE, thr, utl, Math.round(thr * 10), UNIT * n,
                P90[n - 1], null, new RunKpi(1000, (int) Math.round(thr * 10), 212.0, 48.0, thr * 10 / 6.0, 0.068, 171_400L));
    }

    static List<Run> runs(long estimateId, int maxCount) {
        List<Run> runs = new ArrayList<>();
        for (int n = 1; n <= maxCount; n++) {
            runs.add(run(estimateId, n));
        }
        return runs;
    }

    static Verification verification(VerifyNoticeCode notice, Comparison comparison) {
        return new Verification("done", notice, 14, notice == VerifyNoticeCode.PARTIAL_FLEET ? 13 : 14, 600, null,
                LocalDateTime.of(2026, 9, 17, 15, 0), comparison);
    }

    static Comparison slowerAtPeak() {
        return new Comparison(new Metric(159.3, 152.0, -7.3), new Metric(384.0, 414.0, 30.0), new Metric(0.068, 0.081, 0.013));
    }

    static EstimateDetailResponse detail(long estimateId, Integer recommended, Integer knee, Verification verification) {
        return new EstimateDetailResponse(estimateId, EstimateStatus.DONE, "iw.hub", 95.0, 60.0, BUDGET,
                recommended, recommended, knee, null, LocalDateTime.of(2026, 9, 17, 14, 13, 50), LocalDateTime.of(2026, 9, 17, 14, 32, 32),
                1122L, null, null, runs(estimateId, 28), verification);
    }

    static WarehouseResponse warehouse() {
        return new WarehouseResponse(1L, "판교 3PL 센터 B동", 60.0, 40.0, 2400.0, 12,
                LocalTime.of(9, 0), LocalTime.of(12, 0), LocalTime.of(13, 0), LocalTime.of(18, 0),
                200L, 1000L, 0.8, 95.0, 60.0, BUDGET);
    }
}
