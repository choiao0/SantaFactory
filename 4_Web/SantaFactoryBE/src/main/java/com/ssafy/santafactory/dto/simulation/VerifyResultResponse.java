package com.ssafy.santafactory.dto.simulation;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import jakarta.validation.constraints.NotBlank;

/** {@code sim.verify.result} 큐 페이로드 (3_FMS/contracts/SIM_VERIFY_CONTRACT.md §3). 모르는 필드는 무시한다. */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record VerifyResultResponse(
        @NotBlank String runId,
        @NotBlank String status,
        String error,
        Long estimateId,
        Artifacts artifacts
) {

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Artifacts(String video) {
    }
}
