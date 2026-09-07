package com.ssafy.santafactory.dto.simulation;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

import java.util.List;

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record SimulationRequest(
        @NotBlank String runId,
        Long seed,
        @NotNull @Valid Warehouse warehouse,
        @NotNull @Valid Amr amr,
        @NotNull @Valid List<Inbound> inbound,
        @NotNull @Valid List<Outbound> outbound
) {

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Warehouse(
            Integer workerCount,
            String inboundStart,
            String inboundEnd,
            String outboundStart,
            String outboundEnd,
            Integer inboundAvg,
            Integer outboundAvg
    ) {
    }

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Amr(
            @NotNull Integer count,
            Double speedEmpty,
            Double speedLoaded,
            Double consumption,
            Double battery,
            Integer chargeTime,
            Double chargeThreshold,
            Integer capacity
    ) {
    }

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Inbound(
            Long inboundId,
            Long arrivedAtS,
            List<Line> lines
    ) {
    }

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Outbound(
            Long orderId,
            Long orderedAtS,
            List<Line> lines
    ) {
    }

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Line(
            Long productId,
            String rackId,
            Integer qty
    ) {
    }
}
