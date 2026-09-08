package com.ssafy.santafactory.dto.estimate;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.List;

/**
 * 견적 생성 응답 — 어느 대수까지 돌리는지와 발행된 run 목록.
 *
 * @param estimateId   생성된 견적 번호
 * @param maxAmrCount  예산·상한으로 산정된 최대 대수 (run 개수와 같다)
 * @param runIds       발행된 시뮬 실행 키 (1대 → maxAmrCount 순)
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record EstimateCreateResponse(Long estimateId, int maxAmrCount, List<String> runIds) {
}
