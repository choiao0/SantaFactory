package com.ssafy.santafactory.dto.estimate;

import java.util.List;

/**
 * {@code POST /estimates/{id}/verify} 의 선택 본문 (S15P21A106-244). 후보 대수를 직접 고를 때만
 * 보낸다 — 비우면 권장 대수 기준 n*−1·n*·n*+1 이다.
 */
public record VerifyCountsRequest(List<Integer> counts) {
}
