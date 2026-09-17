package com.ssafy.santafactory.service.estimate;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * 물리 검증 결과를 계산과 견줄 때 "나빠졌다"고 볼 기준 (S15P21A106-236, 2026-09-17 임시 결정 — 결과가 이상하면 yml 로 조정).
 * {@code EstimateProperties} 에 넣지 않은 이유는 테스트 5개 파일의 위치 인자 리터럴을 전부 고쳐야 해서다.
 *
 * @param leadTimeP90Tolerance   주문 처리 시간(p90) 증가 비율 상한. 0.10 = 계산보다 10 % 이상 길면 주의
 * @param conflictWaitTolerance  통로 혼잡 비율 증가폭 상한(절대값). 0.01 = 1 %p 이상 높으면 주의
 */
@ConfigurationProperties(prefix = "estimate.verify-compare")
public record VerifyCompareProperties(
        @DefaultValue("0.10") double leadTimeP90Tolerance,
        @DefaultValue("0.01") double conflictWaitTolerance
) {
}
