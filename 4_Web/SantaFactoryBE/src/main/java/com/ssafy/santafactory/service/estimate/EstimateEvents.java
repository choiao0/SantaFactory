package com.ssafy.santafactory.service.estimate;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.entity.estimate.ReasonCode;

import java.util.List;

/**
 * 견적 진행 이벤트. {@link EstimateService} 가 트랜잭션 안에서 발행하고, SSE 스트림이 커밋 뒤에 받아
 * 브라우저로 밀어준다. 리스너가 DB 를 다시 읽지 않도록 필요한 값을 이벤트에 다 담는다.
 *
 * <p>SSE 페이로드로 그대로 나가므로 다른 응답 DTO 와 같이 {@code snake_case} 로 직렬화한다.
 */
public final class EstimateEvents {

    private EstimateEvents() {
    }

    /**
     * 견적의 run 행이 전부 커밋됐다 — 이제 요청 큐에 발행해도 된다. SSE 로 나가지 않는 내부 이벤트.
     * 트랜잭션 안에서 발행하면 워커의 첫 응답(running)이 커밋 전에 돌아와 "모르는 run" 으로 버려질 수
     * 있어, 발행은 {@link SimRequestDispatcher} 가 커밋 뒤에 한다.
     */
    public record RunsQueued(Long estimateId, SimulationRequest request, List<Integer> amrCounts) {
    }

    /** run 하나의 상태가 바뀌었다 (RUNNING / DONE / FAILED / TIMEOUT). */
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record RunUpdated(Long estimateId, EstimateDetailResponse.Run run) {
    }

    /** 견적이 더 이상 진행 중이 아니다 (DONE / PARTIAL / CANCELLED). */
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record EstimateFinished(
            Long estimateId,
            EstimateStatus status,
            Integer recommendedCount,
            Integer kneeCount,
            ReasonCode reasonCode
    ) {
    }

    /**
     * 물리 검증(Isaac) 결과가 도착했다 (status: done/failed), 또는 아직 결과를 기다리는 중이라는
     * 구독 시작 스냅샷이다(status: PENDING, {@link VerifyEventStream} 이 로컬로만 만든다).
     */
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record EstimateVerified(Long estimateId, String status, String videoUrl,
                                   String videoSideUrl, String error) {
    }
}
