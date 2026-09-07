package com.ssafy.santafactory.service.estimate;

/**
 * 견적 요청자가 제시한 목표. {@code Estimates} 의 목표 3개 스냅샷과 1:1 대응한다.
 *
 * @param targetThroughputPercent  목표 출고 처리율 % ({@code Estimates.target_throughput})
 * @param targetUtilizationPercent 목표 AMR 가동률 % ({@code Estimates.target_utilization})
 * @param budgetLimit              목표 구축 비용, 원 ({@code Estimates.budget_limit})
 */
public record EstimateGoal(double targetThroughputPercent, double targetUtilizationPercent, long budgetLimit) {
}
