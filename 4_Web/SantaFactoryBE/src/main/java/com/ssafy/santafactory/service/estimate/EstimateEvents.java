package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.entity.estimate.ReasonCode;

/**
 * 견적 진행 이벤트. {@link EstimateService} 가 트랜잭션 안에서 발행하고, SSE 스트림이 커밋 뒤에 받아
 * 브라우저로 밀어준다. 리스너가 DB 를 다시 읽지 않도록 필요한 값을 이벤트에 다 담는다.
 */
public final class EstimateEvents {

    private EstimateEvents() {
    }

    /** run 하나의 상태가 바뀌었다 (DONE / FAILED / TIMEOUT). */
    public record RunUpdated(Long estimateId, EstimateDetailResponse.Run run) {
    }

    /** 견적이 더 이상 진행 중이 아니다 (DONE / PARTIAL / CANCELLED). */
    public record EstimateFinished(
            Long estimateId,
            EstimateStatus status,
            Integer recommendedCount,
            Integer kneeCount,
            ReasonCode reasonCode
    ) {
    }
}
