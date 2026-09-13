package com.ssafy.santafactory.dto.admin;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.entity.estimate.ReasonCode;
import com.ssafy.santafactory.entity.member.Member;
import java.time.LocalDateTime;

/**
 * 관리자 화면의 견적 한 행 — "오늘 어떤 회사가 뭘 신청했나"를 보는 용도다.
 *
 * <p>고객 목록({@code GET /api/estimates})과 달리 <b>회사·담당자·창고</b>를 함께 담는다.
 * 영업이 매일 여는 화면이 이쪽이므로 누가 낸 견적인지가 행에 보여야 한다.
 *
 * <p>창고 주인이 없는 견적은 있을 수 없다(생성 API 가 내 창고만 허용) 지만, 시드 창고가
 * 아직 귀속되지 않은 순간이 있을 수 있어 회원 필드는 null 을 허용한다.
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AdminEstimateResponse(
        Long estimateId,
        EstimateStatus status,
        String amrModel,
        Integer recommendedCount,
        ReasonCode reasonCode,
        Long warehouseId,
        String warehouseName,
        Long memberId,
        String memberName,
        String company,
        String phone,
        LocalDateTime createdAt,
        LocalDateTime completedAt
) {

    public static AdminEstimateResponse from(Estimate estimate) {
        var warehouse = estimate.getWarehouse();
        Member owner = warehouse == null ? null : warehouse.getMember();
        return new AdminEstimateResponse(
                estimate.getId(),
                estimate.getStatus(),
                estimate.getAmrModel(),
                estimate.getRecommendedCount(),
                estimate.getReasonCode(),
                warehouse == null ? null : warehouse.getId(),
                warehouse == null ? null : warehouse.getName(),
                owner == null ? null : owner.getId(),
                owner == null ? null : owner.getName(),
                owner == null ? null : owner.getCompany(),
                owner == null ? null : owner.getPhone(),
                estimate.getCreatedAt(),
                estimate.getCompletedAt());
    }
}
