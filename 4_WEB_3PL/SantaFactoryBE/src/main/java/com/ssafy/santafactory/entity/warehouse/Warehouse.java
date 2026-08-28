package com.ssafy.santafactory.entity.warehouse;

import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Column;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Entity
@Table(name = "Warehouses")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Warehouse {

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
}
