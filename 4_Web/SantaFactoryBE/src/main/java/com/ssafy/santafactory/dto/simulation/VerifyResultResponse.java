package com.ssafy.santafactory.dto.simulation;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import jakarta.validation.constraints.NotBlank;

/**
 * {@code sim.verify.result} 큐 페이로드 (3_FMS/contracts/SIM_VERIFY_CONTRACT.md §3). 모르는 필드는 무시한다 —
 * 계약에는 runner·rtf_mean·counters 같은 운영용 키가 더 있고 여기서는 견적에 남길 것만 읽는다.
 *
 * <p>{@code verify}·{@code kpi} 는 계약에 있던 필드를 읽기 시작한 것이다(S15P21A106-236) — 옛 워커가 보내지 않으면 null.
 * {@code kpi} 는 DES 결과와 같은 14개 키라 {@link SimulationResponse.Kpi} 를 그대로 쓴다.
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
@JsonIgnoreProperties(ignoreUnknown = true)
public record VerifyResultResponse(
        @NotBlank String runId,
        @NotBlank String status,
        String error,
        Long estimateId,
        String sourceRunId,
        Artifacts artifacts,
        Verify verify,
        SimulationResponse.Kpi kpi,
        /**
         * 러너 {@code Runner/Physics} 파싱 결과 (명세 §C, S15P21A106-244). 없거나 깨졌으면 null —
         * 그때 물리 판정은 {@link com.ssafy.santafactory.service.estimate.PhysicsVerdict.Verdict#NA} 다.
         */
        PhysicsMetrics physics
) {

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    @JsonIgnoreProperties(ignoreUnknown = true)
    /**
     * 시점별 영상 키. {@code video} 는 상단 시점이고 {@code videoFpv} 는 1인칭 시점이다 —
     * 1인칭을 찍지 않는 옛 러너는 보내지 않으므로 null 이 될 수 있다(계약 §3).
     */
    public record Artifacts(String video, String videoFpv) {
    }

    /** 러너가 본 실행 정보. {@code fms.warnings} 가 null 이 아니면 견적과 다른 조건에서 돌았다(계약 §3). */
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Verify(Integer nRobots, Integer robotsOnline, Integer windowS, String reason, Fms fms) {
    }

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Fms(String status, String error, JsonNode warnings) {
    }
}
