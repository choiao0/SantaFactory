package com.ssafy.santafactory.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

import com.ssafy.santafactory.dto.warehouse.WarehouseCreateRequest;
import com.ssafy.santafactory.dto.warehouse.WarehouseResponse;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.entity.warehouse.WarehouseStatus;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.repository.WarehouseRepository;
import java.time.LocalTime;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class WarehouseServiceTest {

    @Mock
    WarehouseRepository warehouseRepository;

    @InjectMocks
    WarehouseService service;

    @Test
    void creates_a_warehouse_from_the_form_values_and_fills_layout_defaults() {
        ArgumentCaptor<Warehouse> saved = ArgumentCaptor.captor();
        when(warehouseRepository.save(saved.capture())).thenAnswer(call -> call.getArgument(0));

        WarehouseResponse response = service.create(new WarehouseCreateRequest(
                null, null, null, 4,
                LocalTime.of(1, 0), LocalTime.of(9, 0),
                LocalTime.of(13, 0), LocalTime.of(18, 0),
                480L, 500L, null, 90.0, null, 600_000_000L));

        Warehouse w = saved.getValue();
        assertThat(w.getName()).isEqualTo(WarehouseCreateRequest.DEFAULT_NAME);
        assertThat(w.getWidth()).isEqualTo(WarehouseCreateRequest.DEFAULT_WIDTH);
        assertThat(w.getLength()).isEqualTo(WarehouseCreateRequest.DEFAULT_LENGTH);
        assertThat(w.getArea()).isEqualTo(WarehouseCreateRequest.DEFAULT_WIDTH * WarehouseCreateRequest.DEFAULT_LENGTH);
        assertThat(w.getStatus()).isEqualTo(WarehouseStatus.OUTBOUND);
        assertThat(w.getWorkerCount()).isEqualTo(4);
        assertThat(w.getInboundAvg()).isEqualTo(480L);
        assertThat(w.getOutboundAvg()).isEqualTo(500L);
        assertThat(w.getOutboundRate()).isZero();
        assertThat(w.getTargetThroughput()).isEqualTo(90.0);
        assertThat(w.getTargetUtilization()).isEqualTo(WarehouseCreateRequest.DEFAULT_TARGET_UTILIZATION);
        assertThat(w.getBudgetLimit()).isEqualTo(600_000_000L);

        // 시간대는 TIMESTAMP 컬럼에 맞춰 날짜를 붙이지만, 응답에서는 다시 시각만 돌려준다
        assertThat(w.getOutboundStart().toLocalTime()).isEqualTo(LocalTime.of(13, 0));
        assertThat(w.getOutboundEnd().toLocalDate()).isEqualTo(w.getOutboundStart().toLocalDate());
        assertThat(response.inboundStart()).isEqualTo(LocalTime.of(1, 0));
        assertThat(response.outboundEnd()).isEqualTo(LocalTime.of(18, 0));
    }

    @Test
    void keeps_explicit_layout_and_goal_values() {
        when(warehouseRepository.save(any())).thenAnswer(call -> call.getArgument(0));

        WarehouseResponse response = service.create(new WarehouseCreateRequest(
                "테스트 창고", 24.0, 14.0, 2,
                LocalTime.of(8, 0), null,
                LocalTime.of(9, 0), null,
                0L, 100L, 95.0, 80.0, 60.0, 1_000L));

        assertThat(response.name()).isEqualTo("테스트 창고");
        assertThat(response.area()).isEqualTo(336.0);
        assertThat(response.inboundEnd()).isNull();
        assertThat(response.outboundRate()).isEqualTo(95.0);
        assertThat(response.targetUtilization()).isEqualTo(60.0);
    }

    @Test
    void unknown_warehouse_is_a_404() {
        when(warehouseRepository.findById(99L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.get(99L))
                .isInstanceOf(GlobalException.class)
                .extracting(e -> ((GlobalException) e).getErrorCode())
                .isEqualTo(ErrorCode.WAREHOUSE_NOT_FOUND);
    }
}
