package com.ssafy.santafactory.global.auth;

import static com.ssafy.santafactory.support.TestPrincipals.ADMIN;
import static com.ssafy.santafactory.support.TestPrincipals.user;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.entity.member.Member;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.support.TrialFixtures;
import org.junit.jupiter.api.Test;

/**
 * 체험 모드 (S15P21A106-283) — 새 워커 요청은 막고, 데모 회원의 견적은 가입한 누구나 읽기만 한다.
 */
class TrialModeTest {

    private static final long STRANGER = 3L;

    @Test
    void off_lets_new_requests_through() {
        assertThatCode(() -> TrialFixtures.off().rejectNewRequests()).doesNotThrowAnyException();
    }

    @Test
    void on_rejects_new_requests_with_the_trial_code() {
        assertThatThrownBy(() -> TrialFixtures.on().rejectNewRequests())
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.TRIAL_READ_ONLY);
    }

    @Test
    void the_demo_members_warehouse_is_the_showcase_only_while_on() {
        Warehouse demos = warehouseOf(TrialFixtures.DEMO_EMAIL);

        assertThat(TrialFixtures.on().isShowcase(demos)).isTrue();
        assertThat(TrialFixtures.off().isShowcase(demos)).isFalse();
    }

    @Test
    void someone_elses_or_an_orphan_warehouse_is_never_the_showcase() {
        assertThat(TrialFixtures.on().isShowcase(warehouseOf("someone@test"))).isFalse();
        assertThat(TrialFixtures.on().isShowcase(mock(Warehouse.class))).isFalse();   // 주인 없는 창고
    }

    @Test
    void without_a_demo_account_there_is_nothing_to_share() {
        TrialMode trial = TrialFixtures.onWithoutDemoAccount();

        assertThat(trial.showcaseOwnerEmail()).isEmpty();
        assertThat(trial.isShowcase(warehouseOf(TrialFixtures.DEMO_EMAIL))).isFalse();
    }

    // ── 소유권: 읽기와 쓰기를 가른다 ───────────────────────────────────────

    @Test
    void anyone_signed_in_can_read_a_demo_estimate_while_on() {
        Estimate demo = estimateIn(warehouseOf(TrialFixtures.DEMO_EMAIL));

        assertThatCode(() -> new OwnershipGuard(TrialFixtures.on()).checkEstimateReadable(demo, user(STRANGER)))
                .doesNotThrowAnyException();
    }

    @Test
    void a_demo_estimate_stays_private_while_off() {
        Estimate demo = estimateIn(warehouseOf(TrialFixtures.DEMO_EMAIL));

        assertThatThrownBy(() -> new OwnershipGuard(TrialFixtures.off()).checkEstimateReadable(demo, user(STRANGER)))
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.ESTIMATE_NOT_FOUND);
    }

    @Test
    void reading_does_not_open_other_members_estimates() {
        Estimate others = estimateIn(warehouseOf("someone@test"));

        assertThatThrownBy(() -> new OwnershipGuard(TrialFixtures.on()).checkEstimateReadable(others, user(STRANGER)))
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.ESTIMATE_NOT_FOUND);
        assertThatCode(() -> new OwnershipGuard(TrialFixtures.on()).checkEstimateReadable(others, ADMIN))
                .doesNotThrowAnyException();
    }

    @Test
    void writing_to_a_demo_estimate_is_still_for_its_owner_only() {
        Estimate demo = estimateIn(warehouseOf(TrialFixtures.DEMO_EMAIL));

        // 삭제·취소·검증이 쓰는 검사 — 체험 모드여도 남이 데모 견적을 지우지 못한다
        assertThatThrownBy(() -> new OwnershipGuard(TrialFixtures.on()).checkEstimate(demo, user(STRANGER)))
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.ESTIMATE_NOT_FOUND);
    }

    private static Warehouse warehouseOf(String ownerEmail) {
        Warehouse warehouse = mock(Warehouse.class);
        when(warehouse.getMember()).thenReturn(Member.signUp(ownerEmail, "x", "주인", "회사", "01000000000"));
        return warehouse;
    }

    private static Estimate estimateIn(Warehouse warehouse) {
        return Estimate.open(warehouse, "iw.hub", 95.0, 80.0, 300_000_000L);
    }
}
