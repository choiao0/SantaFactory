package com.ssafy.santafactory.service;

import com.ssafy.santafactory.dto.robot.RobotModelResponse;
import com.ssafy.santafactory.repository.RobotRepository;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class RobotService {

    private final RobotRepository robotRepository;

    @Transactional(readOnly = true)
    public List<RobotModelResponse> models() {
        return robotRepository.findOnePerModel().stream().map(RobotModelResponse::from).toList();
    }
}
