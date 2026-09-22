package com.ssafy.santafactory.dto.estimate;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.entity.estimate.ReasonCode;
import com.ssafy.santafactory.entity.estimate.RunStatus;
import com.ssafy.santafactory.entity.simulation.RunKpiDetail;
import com.ssafy.santafactory.entity.simulation.SimScenario;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 견적 상태 + 대수별 결과표 + 권장 대수 (명세 §3-1 GET /estimates/{id}).
 *
 * @param recommendedCount 3조건 만족 최소 대수. 없으면 null 이고 이때만 reasonCode 가 채워진다
 * @param minimalCount     같은 조건을 만족하는 대수 중 가장 적은 대수. 권장과 같을 수 있다
 * @param kneeCount        이 대수 이상은 늘려도 처리율이 거의 오르지 않는다
 * @param elapsedSeconds   생성 → 완료 소요시간(초). 진행 중이면 null (90초 목표 측정)
 * @param verifyVideoUrl   물리 검증 영상(상단 시점)의 presigned GET URL. 만료가 있어 저장하지 말고 조회할 때마다 받는다.
 * @param verifyVideoSideUrl 같은 검증의 측면 시점. 측면을 찍지 않은 회차는 null 이고 화면은 상단만 보여준다.
 *                         검증 전이거나 영상이 없으면 null
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record EstimateDetailResponse(
        Long estimateId,
        EstimateStatus status,
        String amrModel,
        Double targetThroughput,
        Double targetUtilization,
        Long budgetLimit,
        Integer recommendedCount,
        Integer minimalCount,
        Integer kneeCount,
        ReasonCode reasonCode,
        LocalDateTime createdAt,
        LocalDateTime completedAt,
        Long elapsedSeconds,
        String verifyVideoUrl,
        String verifyVideoSideUrl,
        List<Run> runs,
        /** 물리 검증 결과와 계산 대비 (S15P21A106-236). 검증 전이면 null. */
        Verification verification
) {

    /** 대수 1개 = 표의 한 행. */
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Run(
            String runId,
            Integer amrCount,
            RunStatus status,
            Double throughput,
            Double utilization,
            Long outbound,
            Long totalCost,
            /**
             * 주문 리드타임 p90(초) — 이 대수로 돌렸을 때 주문 10건 중 9건이 끝난 시간.
             * 판정에는 쓰지 않는다({@code estimate.lead-time-p90-limit} 미설정). 무릎 이후 구간을
             * 설명하는 유일한 지표라 화면에 내보낸다 — 처리율이 포화한 뒤에도 이 값은 계속 짧아진다.
             */
            Double leadTimeP90,
            String error,
            /** 판정 밖 상세 지표 (S15P21A106-236). 시뮬이 하나도 안 줬거나 옛 run 이면 null. */
            RunKpi kpi
    ) {

        public static Run from(SimScenario scenario) {
            return new Run(
                    scenario.getRunId(),
                    scenario.getAmrCount(),
                    scenario.getStatus(),
                    scenario.getThroughput(),
                    scenario.getUtilization(),
                    scenario.getOutbound(),
                    scenario.getTotalCost(),
                    scenario.getLeadTimeP90(),
                    scenario.getError(),
                    RunKpi.from(scenario.getKpiDetail()));
        }
    }

    /** 명세 §1-2 kpi 의 키 이름·단위(초·m·0~1 비율) 그대로. */
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record RunKpi(
            Integer ordersTotal,
            Integer ordersCompleted,
            Double leadTimeMeanS,
            Double queueTimeMeanS,
            Double throughputOrdersPerH,
            Double conflictWaitRatio,
            Long distanceTotalM
    ) {

        public static RunKpi from(RunKpiDetail detail) {
            if (detail == null) {
                return null;
            }
            return new RunKpi(detail.getOrdersTotal(), detail.getOrdersCompleted(), detail.getLeadTimeMeanS(),
                    detail.getQueueTimeMeanS(), detail.getThroughputOrdersPerH(), detail.getConflictWaitRatio(),
                    detail.getDistanceTotalM());
        }
    }

    /**
     * 물리 검증 결과 — 정상 종료 여부와, 권장 대수의 계산 결과 대비 피크 10분 창의 차이.
     * {@code comparison} 은 notice 가 비교를 허용할 때만 있고, 각 Metric 의 {@code diff} 는 검증 − 예상(지표 단위 그대로)이다.
     */
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Verification(
            String status,
            VerifyNoticeCode notice,
            Integer nRobots,
            Integer robotsOnline,
            Integer windowS,
            String error,
            LocalDateTime verifiedAt,
            Comparison comparison
    ) {

        @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
        public record Comparison(Metric throughputOrdersPerH, Metric leadTimeP90S, Metric conflictWaitRatio) {
        }

        @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
        public record Metric(Double expected, Double verified, Double diff) {
        }
    }

    public static EstimateDetailResponse of(Estimate estimate, List<SimScenario> runs,
                                           String verifyVideoUrl, String verifyVideoSideUrl,
                                            Verification verification) {
        return new EstimateDetailResponse(
                estimate.getId(),
                estimate.getStatus(),
                estimate.getAmrModel(),
                estimate.getTargetThroughput(),
                estimate.getTargetUtilization(),
                estimate.getBudgetLimit(),
                estimate.getRecommendedCount(),
                estimate.getMinimalCount(),
                estimate.getKneeCount(),
                estimate.getReasonCode(),
                estimate.getCreatedAt(),
                estimate.getCompletedAt(),
                estimate.elapsedSeconds(),
                verifyVideoUrl,
                verifyVideoSideUrl,
                runs.stream().map(Run::from).toList(),
                verification);
    }
}
