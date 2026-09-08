package com.ssafy.santafactory.dto.estimate;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.PositiveOrZero;

/**
 * 견적 요청 — 운영조건(창고) + 목표 + 예산 + AMR 모델.
 *
 * <p>목표 3개와 기종은 비워 보내면 창고의 기본값을 쓴다. 목표·예산은 시뮬에 넘기지 않는다 —
 * 시뮬은 "몇 대로 돌려라"만 알면 되고 판정은 백엔드가 한다.
 *
 * @param warehouseId        운영조건·레이아웃 출처
 * @param amrModel           기종. 없으면 {@code iw.hub}
 * @param targetThroughput   목표 출고 처리율 %. 없으면 창고 값
 * @param targetUtilization  목표 AMR 가동률 %. 없으면 창고 값
 * @param budgetLimit        목표 구축 비용(원). 없으면 창고 값
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record EstimateCreateRequest(
        @NotNull Long warehouseId,
        String amrModel,
        @Positive Double targetThroughput,
        @Positive Double targetUtilization,
        @PositiveOrZero Long budgetLimit
) {

    private static final String DEFAULT_AMR_MODEL = "iw.hub";

    public String amrModelOrDefault() {
        return (amrModel == null || amrModel.isBlank()) ? DEFAULT_AMR_MODEL : amrModel;
    }
}
