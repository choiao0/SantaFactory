package com.ssafy.santafactory.dto.estimate;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.entity.estimate.ReasonCode;
import com.ssafy.santafactory.entity.estimate.RunStatus;
import com.ssafy.santafactory.entity.simulation.SimScenario;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 견적 상태 + 대수별 결과표 + 권장 대수 (명세 §3-1 GET /estimates/{id}).
 *
 * @param recommendedCount 3조건 만족 최소 대수. 없으면 null 이고 이때만 reasonCode 가 채워진다
 * @param kneeCount        이 대수 이상은 늘려도 처리율이 거의 오르지 않는다
 * @param elapsedSeconds   생성 → 완료 소요시간(초). 진행 중이면 null (90초 목표 측정)
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
        Integer kneeCount,
        ReasonCode reasonCode,
        LocalDateTime createdAt,
        LocalDateTime completedAt,
        Long elapsedSeconds,
        List<Run> runs
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
            String error
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
                    scenario.getError());
        }
    }

    public static EstimateDetailResponse of(Estimate estimate, List<SimScenario> runs) {
        return new EstimateDetailResponse(
                estimate.getId(),
                estimate.getStatus(),
                estimate.getAmrModel(),
                estimate.getTargetThroughput(),
                estimate.getTargetUtilization(),
                estimate.getBudgetLimit(),
                estimate.getRecommendedCount(),
                estimate.getKneeCount(),
                estimate.getReasonCode(),
                estimate.getCreatedAt(),
                estimate.getCompletedAt(),
                estimate.elapsedSeconds(),
                runs.stream().map(Run::from).toList());
    }
}
