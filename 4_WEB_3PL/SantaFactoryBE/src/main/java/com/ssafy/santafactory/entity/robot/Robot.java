package com.ssafy.santafactory.entity.robot;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Entity
@Table(name = "Robots")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Robot {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "robot_id")
    private Long id;

    @Column(name = "model", nullable = false, length = 100)
    private String model;

    @Column(name = "battery", nullable = false)
    private Double battery;

    @Column(name = "speed", nullable = false)
    private Double speed;

    @Column(name = "capacity", nullable = false)
    private Integer capacity;

    @Column(name = "price", nullable = false)
    private Integer price;

    @Column(name = "cost", nullable = false)
    private Integer cost;

    @Column(name = "x", nullable = false)
    private Double x;

    @Column(name = "y", nullable = false)
    private Double y;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false)
    private RobotStatus status;
}
