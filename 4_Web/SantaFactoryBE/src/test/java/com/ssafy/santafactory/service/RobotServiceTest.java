package com.ssafy.santafactory.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.ssafy.santafactory.dto.robot.RobotModelResponse;
import com.ssafy.santafactory.entity.robot.Robot;
import com.ssafy.santafactory.repository.RobotRepository;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class RobotServiceTest {

    @Mock
    RobotRepository robotRepository;

    @InjectMocks
    RobotService service;

    @Test
    void maps_one_catalog_row_per_model() {
        Robot iwhub = mock(Robot.class);
        when(iwhub.getModel()).thenReturn("iw.hub");
        when(iwhub.getSpeed()).thenReturn(2.0);
        when(iwhub.getCapacity()).thenReturn(200);
        when(iwhub.getBattery()).thenReturn(100.0);
        when(iwhub.getPrice()).thenReturn(15_000_000);
        when(iwhub.getCost()).thenReturn(500_000);
        when(robotRepository.findOnePerModel()).thenReturn(List.of(iwhub));

        List<RobotModelResponse> models = service.models();

        assertThat(models).hasSize(1);
        assertThat(models.get(0).model()).isEqualTo("iw.hub");
        assertThat(models.get(0).price()).isEqualTo(15_000_000);
        assertThat(models.get(0).cost()).isEqualTo(500_000);
    }
}
