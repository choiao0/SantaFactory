package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.entity.estimate.ReasonCode;

/**
 * 견적 판정 결과.
 *
 * @param recommendedCount 3조건을 모두 만족하는 최소 대수. 없으면 null
 * @param kneeCount        대수를 늘려도 처리량이 거의 늘지 않기 시작하는 대수. 판정 불가면 null
 * @param reasonCode       recommendedCount 가 null 일 때만 채워진다
 */
public record EstimateVerdict(Integer recommendedCount, Integer minimalCount,
                              Integer kneeCount, ReasonCode reasonCode) {

    public static EstimateVerdict of(int recommendedCount, Integer minimalCount, Integer kneeCount) {
        return new EstimateVerdict(recommendedCount, minimalCount, kneeCount, null);
    }

    public static EstimateVerdict none(ReasonCode reasonCode, Integer kneeCount) {
        return new EstimateVerdict(null, null, kneeCount, reasonCode);
    }

    public boolean hasRecommendation() {
        return recommendedCount != null;
    }
}
