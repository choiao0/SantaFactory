package com.ssafy.santafactory.dto.robot;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import com.ssafy.santafactory.entity.robot.Robot;

/**
 * AMR 모델 카드 1장 (01 화면).
 *
 * @param price 대당 단가, 원
 * @param cost  대당 구축·설치비, 원
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record RobotModelResponse(
        String model,
        Double speed,
        Integer capacity,
        Double battery,
        Integer price,
        Integer cost
) {
    public static RobotModelResponse from(Robot robot) {
        return new RobotModelResponse(
                robot.getModel(),
                robot.getSpeed(),
                robot.getCapacity(),
                robot.getBattery(),
                robot.getPrice(),
                robot.getCost());
    }
}
