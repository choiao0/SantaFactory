package com.ssafy.santafactory.dto.simulation;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import jakarta.validation.constraints.NotBlank;

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record SimulationResponse(
        @NotBlank String runId,
        @NotBlank String status,
        String error,
        Kpi kpi
) {

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Kpi(
            Integer ordersTotal,
            Integer ordersCompleted,
            Integer inboundTotal,
            Integer inboundCompleted,

            Long makespanS,
            Double leadTimeMeanS,
            Double leadTimeP90S,
            Double queueTimeMeanS,

            Double throughputOrdersPerH,
            Double throughputTasksPerH,

            Double amrUtilization,
            Double conflictWaitRatio,
            Long distanceTotalM,
            Long chargeDowntimeS
    ) {
    }
}
