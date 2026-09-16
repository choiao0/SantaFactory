package com.ssafy.santafactory.service.estimate;

/**
 * 견적 요청자가 제시한 목표. {@code Estimates} 의 목표 3개 스냅샷과 1:1 대응한다.
 *
 * <p>리드타임 상한만 창고가 아니라 설정({@code estimate.lead-time-p90-limit})에서 온다 — 창고마다
 * 다르게 둘 값인지 팀에서 정하지 않았고, 미설정이면 조건 자체를 건너뛰므로 기존 동작과 같다.
 *
 * @param targetThroughputPercent  목표 출고 처리율 % ({@code Estimates.target_throughput})
 * @param targetUtilizationPercent 목표 AMR 가동률 % ({@code Estimates.target_utilization})
 * @param budgetLimit              목표 구축 비용, 원 ({@code Estimates.budget_limit})
 * @param leadTimeP90LimitSeconds  주문 리드타임 p90 상한, 초. null 이면 리드타임을 보지 않는다
 */
public record EstimateGoal(double targetThroughputPercent, double targetUtilizationPercent, long budgetLimit,
                           Double leadTimeP90LimitSeconds) {
}
