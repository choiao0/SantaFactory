package com.ssafy.santafactory.dto.estimate;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.entity.estimate.ReasonCode;

import java.time.LocalDateTime;

/** 견적 목록의 한 행 — 대수별 결과표는 빼고 결론만 담는다 (명세 §3-1 GET /estimates). */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record EstimateSummaryResponse(
        Long estimateId,
        EstimateStatus status,
        String amrModel,
        Integer recommendedCount,
        Integer kneeCount,
        ReasonCode reasonCode,
        LocalDateTime createdAt,
        LocalDateTime completedAt
) {

    public static EstimateSummaryResponse from(Estimate estimate) {
        return new EstimateSummaryResponse(
                estimate.getId(),
                estimate.getStatus(),
                estimate.getAmrModel(),
                estimate.getRecommendedCount(),
                estimate.getKneeCount(),
                estimate.getReasonCode(),
                estimate.getCreatedAt(),
                estimate.getCompletedAt());
    }
}
