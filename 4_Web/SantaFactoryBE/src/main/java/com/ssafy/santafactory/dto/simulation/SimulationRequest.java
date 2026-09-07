package com.ssafy.santafactory.dto.simulation;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

import java.util.List;

/**
 * 시뮬 실행 1건 요청.
 *
 * <p>{@code horizonS}·{@code shifts}·간격 2개는 <b>고정 시간 실행</b>을 지시한다. 이게 없으면 시뮬이
 * 유한 주문 모드(주문을 다 처리하고 종료)로 돌아 처리율이 전 대수 100 % 가 되고, 견적이 "1대 권장"
 * 같은 틀린 답을 낸다. 실행 시간을 요청에 명시해 그 가정을 계약에 남긴다.
 *
 * @param horizonS     고정 시간 실행 길이(초). 없으면 시뮬이 유한 주문 모드로 돈다
 * @param shifts       입고/출고 교대 토큰열. 전체 시간을 토큰 수로 등분한다 (예: in,in,out,out,out,out)
 * @param inboundGapS  입고 도착 간격(초) 평균
 * @param outboundGapS 출고 도착 간격(초) 평균
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record SimulationRequest(
        @NotBlank String runId,
        Long seed,
        Long horizonS,
        String shifts,
        Double inboundGapS,
        Double outboundGapS,
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
