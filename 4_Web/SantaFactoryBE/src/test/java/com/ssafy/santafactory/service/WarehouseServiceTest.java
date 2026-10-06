package com.ssafy.santafactory.service;

import static com.ssafy.santafactory.support.TestPrincipals.ADMIN;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.santafactory.dto.warehouse.WarehouseCreateRequest;
import com.ssafy.santafactory.dto.warehouse.WarehouseResponse;
import com.ssafy.santafactory.entity.member.Member;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.entity.warehouse.WarehouseStatus;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.global.auth.OwnershipGuard;
import com.ssafy.santafactory.global.auth.TrialMode;
import com.ssafy.santafactory.support.TrialFixtures;
import com.ssafy.santafactory.repository.MemberRepository;
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

    @Mock
    MemberRepository memberRepository;

    @Mock
    OwnershipGuard ownershipGuard;

    /** 목은 아무것도 막지 않는다 — 체험 모드 테스트는 진짜 스위치로 따로 만든다 */
    @Mock
    TrialMode trialMode;

    @InjectMocks
    WarehouseService service;

    /** 소유권은 이 테스트의 관심사가 아니다 — 생성 API 가 세션 회원을 붙이기만 하면 된다. */
    private void givenOwner() {
        when(memberRepository.findById(ADMIN.id()))
                .thenReturn(Optional.of(Member.signUp("owner@test", "x", "주인", "회사", "01000000000")));
    }

    @Test
    void creates_a_warehouse_from_the_form_values_and_fills_layout_defaults() {
        givenOwner();
        ArgumentCaptor<Warehouse> saved = ArgumentCaptor.captor();
        when(warehouseRepository.save(saved.capture())).thenAnswer(call -> call.getArgument(0));

        WarehouseResponse response = service.create(new WarehouseCreateRequest(
                null, null, null, 4,
                LocalTime.of(1, 0), LocalTime.of(9, 0),
                LocalTime.of(13, 0), LocalTime.of(18, 0),
                480L, 500L, null, 90.0, null, 600_000_000L), ADMIN);

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
        givenOwner();
        when(warehouseRepository.save(any())).thenAnswer(call -> call.getArgument(0));

        WarehouseResponse response = service.create(new WarehouseCreateRequest(
                "테스트 창고", 24.0, 14.0, 2,
                LocalTime.of(8, 0), null,
                LocalTime.of(9, 0), null,
                0L, 100L, 95.0, 80.0, 60.0, 1_000L), ADMIN);

        assertThat(response.name()).isEqualTo("테스트 창고");
        assertThat(response.area()).isEqualTo(336.0);
        assertThat(response.inboundEnd()).isNull();
        assertThat(response.outboundRate()).isEqualTo(95.0);
        assertThat(response.targetUtilization()).isEqualTo(60.0);
    }

    /** 새 견적 흐름의 첫 단계라 여기서부터 막는다 — 견적만 막으면 빈 창고가 쌓인다 (S15P21A106-283). */
    @Test
    void trial_mode_rejects_a_new_warehouse_before_saving() {
        WarehouseService trial = new WarehouseService(
                warehouseRepository, memberRepository, ownershipGuard, TrialFixtures.on());

        assertThatThrownBy(() -> trial.create(new WarehouseCreateRequest(
                null, null, null, 4,
                LocalTime.of(1, 0), LocalTime.of(9, 0),
                LocalTime.of(13, 0), LocalTime.of(18, 0),
                480L, 500L, null, 90.0, null, 600_000_000L), ADMIN))
                .isInstanceOf(GlobalException.class)
                .extracting(e -> ((GlobalException) e).getErrorCode())
                .isEqualTo(ErrorCode.TRIAL_READ_ONLY);
        verify(warehouseRepository, never()).save(any());
    }

    @Test
    void unknown_warehouse_is_a_404() {
        when(warehouseRepository.findById(99L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.get(99L, ADMIN))
                .isInstanceOf(GlobalException.class)
                .extracting(e -> ((GlobalException) e).getErrorCode())
                .isEqualTo(ErrorCode.WAREHOUSE_NOT_FOUND);
    }
}
