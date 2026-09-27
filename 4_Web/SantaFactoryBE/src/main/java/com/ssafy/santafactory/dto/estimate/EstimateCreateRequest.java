package com.ssafy.santafactory.dto.estimate;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.PositiveOrZero;

/**
 * 견적 요청 — 운영조건(창고) + 목표 + 예산 + AMR 모델 + (선택) 대수 범위.
 *
 * <p>목표 3개와 기종은 비워 보내면 창고의 기본값을 쓴다. 목표·예산은 시뮬에 넘기지 않는다 —
 * 시뮬은 "몇 대로 돌려라"만 알면 되고 판정은 백엔드가 한다.
 *
 * <p>대수 범위(fleetMin·fleetMax)는 02 FLEET 화면에서 고른 값이다. 둘 다 오면 그 범위를 1대 간격으로
 * 전부 돌리고, 없으면 기존처럼 1대부터 예산으로 살 수 있는 대수까지 돌린다. 권장 대수가 "조건을 만족하는
 * 최소 대수"라 대수를 건너뛰면 정밀도가 떨어지므로 간격은 두지 않는다.
 * 어느 쪽이든 충전 존 상한({@code estimate.max-amr-count})은 넘지 않는다.
 *
 * @param warehouseId        운영조건·레이아웃 출처
 * @param amrModel           기종. 없으면 {@code iw.hub}
 * @param targetThroughput   목표 출고 처리율 %. 없으면 창고 값
 * @param targetUtilization  목표 AMR 가동률 %. 없으면 창고 값
 * @param budgetLimit        목표 구축 비용(원). 없으면 창고 값
 * @param fleetMin           비교할 최소 대수. 없으면 1
 * @param fleetMax           비교할 최대 대수. 없으면 예산 기반 산정
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record EstimateCreateRequest(
        @NotNull Long warehouseId,
        String amrModel,
        @Positive Double targetThroughput,
        @Positive Double targetUtilization,
        @PositiveOrZero Long budgetLimit,
        @Positive Integer fleetMin,
        @Positive Integer fleetMax
) {
    private static final String DEFAULT_AMR_MODEL = "iw.hub";

    public String amrModelOrDefault() {
        return (amrModel == null || amrModel.isBlank()) ? DEFAULT_AMR_MODEL : amrModel;
    }

    /** 범위를 지정했는가 — min 과 max 둘 다 있어야 범위로 본다. */
    @JsonIgnore
    public boolean hasFleetRange() {
        return fleetMin != null && fleetMax != null;
    }

    /** min ≤ max 이어야 한다. 한쪽만 오면 범위로 보지 않으므로 검사하지 않는다. */
    @AssertTrue(message = "최소 대수는 최대 대수보다 클 수 없습니다.")
    @JsonIgnore
    public boolean isFleetRangeOrdered() {
        return !hasFleetRange() || fleetMin <= fleetMax;
    }
}
