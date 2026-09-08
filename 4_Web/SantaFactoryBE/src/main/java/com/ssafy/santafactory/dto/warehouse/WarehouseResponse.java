package com.ssafy.santafactory.dto.warehouse;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import java.time.LocalDateTime;
import java.time.LocalTime;

/** 창고 운영 조건 — 01 화면 폼에 그대로 채울 수 있는 형태. 시각은 "HH:mm". */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record WarehouseResponse(
        Long warehouseId,
        String name,
        Double width,
        Double length,
        Double area,
        Integer workerCount,
        LocalTime inboundStart,
        LocalTime inboundEnd,
        LocalTime outboundStart,
        LocalTime outboundEnd,
        Long inboundAvg,
        Long outboundAvg,
        Double outboundRate,
        Double targetThroughput,
        Double targetUtilization,
        Long budgetLimit
) {
    public static WarehouseResponse from(Warehouse w) {
        return new WarehouseResponse(
                w.getId(),
                w.getName(),
                w.getWidth(),
                w.getLength(),
                w.getArea(),
                w.getWorkerCount(),
                time(w.getInboundStart()),
                time(w.getInboundEnd()),
                time(w.getOutboundStart()),
                time(w.getOutboundEnd()),
                w.getInboundAvg(),
                w.getOutboundAvg(),
                w.getOutboundRate(),
                w.getTargetThroughput(),
                w.getTargetUtilization(),
                w.getBudgetLimit());
    }

    private static LocalTime time(LocalDateTime value) {
        return value == null ? null : value.toLocalTime();
    }
}
