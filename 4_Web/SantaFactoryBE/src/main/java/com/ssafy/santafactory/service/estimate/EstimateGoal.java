package com.ssafy.santafactory.service.estimate;

/**
 * 견적 요청자가 제시한 목표.
 *
 * @param targetOrdersPerH   목표 처리량 (주문/시간)
 * @param targetUtilization  목표 가동률 (0~1)
 * @param budget             예산 (원)
 */
public record EstimateGoal(double targetOrdersPerH, double targetUtilization, long budget) {
}
