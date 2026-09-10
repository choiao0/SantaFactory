package com.ssafy.santafactory.dto.simulation;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * {@code sim.verify.request} 큐 페이로드 (3_FMS/contracts/SIM_VERIFY_CONTRACT.md §2).
 *
 * <p>{@code runId} 는 host-orch 가 "지금 처리 중인 작업과 같은가"를 판단하는 실제 키다(같으면 재전송으로
 * 취급, 멱등) — 견적당 검증은 정상적으로 한 번만 돌아서 견적 id 로 고정한다. {@code sourceRunId} 는
 * 반대로 host-orch 로직 어디에도 안 쓰이고 결과에 그대로 돌아오기만 하는 추적용 꼬리표라,
 * 이 둘을 하나로 합치면 안 된다.
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record VerifyRequest(
        String runId,
        int nRobots,
        long windowS,
        String sourceRunId,
        Long estimateId,
        long seed
) {
}
