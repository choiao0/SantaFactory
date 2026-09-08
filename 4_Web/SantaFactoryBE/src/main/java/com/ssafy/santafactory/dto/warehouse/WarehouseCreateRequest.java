package com.ssafy.santafactory.dto.warehouse;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.PositiveOrZero;
import java.time.LocalTime;

/**
 * 창고 운영 조건 입력 (01 WAREHOUSE 화면).
 *
 * <p>레이아웃은 고정 맵이라 폭·길이를 안 보내면 시드(품고)와 같은 값을 쓴다. 목표·예산 중
 * 화면에 없는 가동률은 비워 보내면 기본값을 쓴다.
 *
 * @param name              창고 이름. 없으면 기본 이름
 * @param width             가로(m). 없으면 고정 맵 값
 * @param length            세로(m). 없으면 고정 맵 값
 * @param workerCount       작업자 수
 * @param inboundStart      입고 시작 "HH:mm"
 * @param inboundEnd        입고 종료 "HH:mm"
 * @param outboundStart     출고 시작 "HH:mm"
 * @param outboundEnd       출고 종료 "HH:mm"
 * @param inboundAvg        일 평균 입고 건수
 * @param outboundAvg       일 평균 출고 주문 건수
 * @param outboundRate      현재 출고 처리율 %. 없으면 0
 * @param targetThroughput  목표 출고 처리율 %. 없으면 기본값
 * @param targetUtilization 목표 AMR 가동률 %. 없으면 기본값
 * @param budgetLimit       최대 구축 예산, 원
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record WarehouseCreateRequest(
        String name,
        @Positive Double width,
        @Positive Double length,
        @NotNull @Positive Integer workerCount,
        @NotNull LocalTime inboundStart,
        LocalTime inboundEnd,
        @NotNull LocalTime outboundStart,
        LocalTime outboundEnd,
        @NotNull @PositiveOrZero Long inboundAvg,
        @NotNull @PositiveOrZero Long outboundAvg,
        @PositiveOrZero Double outboundRate,
        @Positive Double targetThroughput,
        @PositiveOrZero Double targetUtilization,
        @NotNull @PositiveOrZero Long budgetLimit
) {
    /** 고정 맵(3_FMS/map)과 시드 창고의 크기. */
    public static final String DEFAULT_NAME = "품고";
    public static final double DEFAULT_WIDTH = 110.0;
    public static final double DEFAULT_LENGTH = 90.0;
    /** 시드 창고의 목표값과 같다. */
    public static final double DEFAULT_TARGET_THROUGHPUT = 95.0;
    public static final double DEFAULT_TARGET_UTILIZATION = 80.0;

    public String nameOrDefault() {
        return (name == null || name.isBlank()) ? DEFAULT_NAME : name;
    }

    public double widthOrDefault() {
        return width == null ? DEFAULT_WIDTH : width;
    }

    public double lengthOrDefault() {
        return length == null ? DEFAULT_LENGTH : length;
    }

    public double outboundRateOrDefault() {
        return outboundRate == null ? 0.0 : outboundRate;
    }

    public double targetThroughputOrDefault() {
        return targetThroughput == null ? DEFAULT_TARGET_THROUGHPUT : targetThroughput;
    }

    public double targetUtilizationOrDefault() {
        return targetUtilization == null ? DEFAULT_TARGET_UTILIZATION : targetUtilization;
    }
}
