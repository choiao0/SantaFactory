package com.ssafy.santafactory.dto.simulation;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.List;

/**
 * {@code sim.verify.request} 큐 페이로드 (3_FMS/contracts/SIM_VERIFY_CONTRACT.md §2).
 *
 * <p>{@code runId} 는 host-orch 가 "지금 처리 중인 작업과 같은가"를 판단하는 실제 키다(같으면 재전송으로
 * 취급, 멱등) — 견적당 검증은 정상적으로 한 번만 돌아서 견적 id 로 고정한다. {@code sourceRunId} 는
 * 반대로 host-orch 로직 어디에도 안 쓰이고 결과에 그대로 돌아오기만 하는 추적용 꼬리표라,
 * 이 둘을 하나로 합치면 안 된다.
 *
 * <p>{@code scenario} 는 견적이 DES 스윕에 실제로 쓴 출고 주문 전체를 그대로 싣는다({@code Estimate.outboundOrdersJson}).
 * 어느 구간이 물리 검증의 피크인지는 백엔드가 고르지 않는다 — 시뮬/FMS 쪽이 전체 목록을 받아 자체적으로
 * 정한다(계약의 {@code scenario.window_start_s} 는 그쪽 몫이라 여기선 보내지 않는다).
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record VerifyRequest(
        String runId,
        int nRobots,
        long windowS,
        String sourceRunId,
        Long estimateId,
        long seed,
        Scenario scenario
) {

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Scenario(long seed, Orders orders) {
    }

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Orders(Object meta, List<SimulationRequest.Outbound> outbound) {
    }
}
