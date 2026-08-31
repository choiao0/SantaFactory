package com.ssafy.santafactory.entity.simulation;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Entity
@Table(name = "SimScenarios")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class SimScenario {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "scenario_id")
    private Long id;

    @Column(name = "round", nullable = false)
    private Long round;

    @Column(name = "amr_count")
    private Integer amrCount;

    @Column(name = "utilization")
    private Double utilization;

    @Column(name = "outbound")
    private Long outbound;

    @Column(name = "throughput")
    private Double throughput;

    @Column(name = "total_cost")
    private Long totalCost;
}
