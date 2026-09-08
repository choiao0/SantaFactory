package com.ssafy.santafactory.entity.warehouse;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Entity
@Table(name = "Warehouses")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Warehouse {

    /**
     * 시간대 컬럼이 TIMESTAMP 라 날짜가 필요하다. 견적 계산은 시각 차이만 쓰므로 날짜는 의미가 없고,
     * 시드(R__seed_demo.sql)와 같은 날짜로 고정해 두어 값이 섞이지 않게 한다.
     */
    private static final LocalDate TIME_ANCHOR = LocalDate.of(2026, 1, 1);

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "warehouse_id")
    private Long id;

    @Column(name = "name", nullable = false)
    private String name;

    @Column(name = "area", nullable = false)
    private Double area;

    @Column(name = "width", nullable = false)
    private Double width;

    @Column(name = "length", nullable = false)
    private Double length;

    @Column(name = "worker_count", nullable = false)
    private Integer workerCount;

    @Column(name = "inbound_start", nullable = false)
    private LocalDateTime inboundStart;

    @Column(name = "inbound_end")
    private LocalDateTime inboundEnd;

    @Column(name = "outbound_start", nullable = false)
    private LocalDateTime outboundStart;

    @Column(name = "outbound_end")
    private LocalDateTime outboundEnd;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false)
    private WarehouseStatus status;

    @Column(name = "inbound_avg", nullable = false)
    private Long inboundAvg;

    @Column(name = "outbound_avg", nullable = false)
    private Long outboundAvg;

    @Column(name = "outbound_rate", nullable = false)
    private Double outboundRate;

    @Column(name = "target_throughput", nullable = false)
    private Double targetThroughput;

    @Column(name = "target_utilization", nullable = false)
    private Double targetUtilization;

    @Column(name = "budget_limit", nullable = false)
    private Long budgetLimit;

    private Warehouse(String name, double width, double length, int workerCount,
                      LocalTime inboundStart, LocalTime inboundEnd,
                      LocalTime outboundStart, LocalTime outboundEnd,
                      long inboundAvg, long outboundAvg, double outboundRate,
                      double targetThroughput, double targetUtilization, long budgetLimit) {
        this.name = name;
        this.width = width;
        this.length = length;
        this.area = width * length;
        this.workerCount = workerCount;
        this.inboundStart = anchor(inboundStart);
        this.inboundEnd = anchor(inboundEnd);
        this.outboundStart = anchor(outboundStart);
        this.outboundEnd = anchor(outboundEnd);
        this.status = WarehouseStatus.OUTBOUND;
        this.inboundAvg = inboundAvg;
        this.outboundAvg = outboundAvg;
        this.outboundRate = outboundRate;
        this.targetThroughput = targetThroughput;
        this.targetUtilization = targetUtilization;
        this.budgetLimit = budgetLimit;
    }

    /**
     * 운영 조건 입력으로 창고를 만든다. 레이아웃(폭·길이)은 고정 맵 값이 들어오고 면적은 여기서 계산한다.
     *
     * @param targetThroughput  목표 출고 처리율 %
     * @param targetUtilization 목표 AMR 가동률 %
     * @param budgetLimit       구축 예산, 원
     */
    public static Warehouse create(String name, double width, double length, int workerCount,
                                   LocalTime inboundStart, LocalTime inboundEnd,
                                   LocalTime outboundStart, LocalTime outboundEnd,
                                   long inboundAvg, long outboundAvg, double outboundRate,
                                   double targetThroughput, double targetUtilization, long budgetLimit) {
        return new Warehouse(name, width, length, workerCount,
                inboundStart, inboundEnd, outboundStart, outboundEnd,
                inboundAvg, outboundAvg, outboundRate,
                targetThroughput, targetUtilization, budgetLimit);
    }

    private static LocalDateTime anchor(LocalTime time) {
        return time == null ? null : LocalDateTime.of(TIME_ANCHOR, time);
    }
}
