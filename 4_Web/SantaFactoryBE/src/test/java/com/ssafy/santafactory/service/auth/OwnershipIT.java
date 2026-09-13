package com.ssafy.santafactory.service.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.ssafy.santafactory.dto.auth.SignUpRequest;
import com.ssafy.santafactory.dto.warehouse.WarehouseCreateRequest;
import com.ssafy.santafactory.global.auth.AuthenticatedMember;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.repository.MemberRepository;
import com.ssafy.santafactory.repository.WarehouseRepository;
import com.ssafy.santafactory.service.WarehouseService;
import com.ssafy.santafactory.support.PostgresSupport;
import java.time.LocalTime;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * 회원 사이의 격리 (S15P21A106-186).
 *
 * <p>이 기능의 보안 요체다 — 남의 창고·견적이 <b>없는 것처럼</b> 보여야 한다. 403 을 주면
 * "그 id 의 리소스가 존재한다"가 새어나가 id 를 훑으며 남의 데이터 규모를 셀 수 있다.
 */
@SpringBootTest
class OwnershipIT extends PostgresSupport {

    @Autowired
    AuthService authService;

    @Autowired
    WarehouseService warehouseService;

    @Autowired
    MemberRepository memberRepository;

    @Autowired
    WarehouseRepository warehouseRepository;

    private AuthenticatedMember alice;
    private AuthenticatedMember bob;
    private Long aliceWarehouseId;

    @BeforeEach
    void setUp() {
        warehouseRepository.deleteAllInBatch();
        memberRepository.deleteAllInBatch();

        alice = principal(authService.signUp(
                new SignUpRequest("alice@pumgo.test", "alice-pass-1234", "김담당", "품고물류", "01011112222")).memberId());
        bob = principal(authService.signUp(
                new SignUpRequest("bob@other.test", "bob-pass-1234", "박담당", "다른물류", "01033334444")).memberId());

        aliceWarehouseId = warehouseService.create(warehouse(), alice).warehouseId();
    }

    private AuthenticatedMember principal(Long memberId) {
        return new AuthenticatedMember(memberId, "USER");
    }

    private static WarehouseCreateRequest warehouse() {
        return new WarehouseCreateRequest(
                null, null, null, 12,
                LocalTime.of(0, 0), LocalTime.of(9, 0),
                LocalTime.of(13, 0), LocalTime.of(18, 0),
                600L, 800L, 95.0, 95.0, 80.0, 300_000_000L);
    }

    /**
     * 소유자가 실제로 DB 에 남는지 본다. 연관은 LAZY 라 트랜잭션 밖에서 필드를 만지면
     * LazyInitializationException 이 나므로, 프록시 초기화가 필요 없는 id 로만 확인한다.
     */
    @Test
    void a_created_warehouse_belongs_to_the_session_member() {
        var saved = warehouseRepository.findById(aliceWarehouseId).orElseThrow();

        assertThat(saved.getMember()).isNotNull();
        assertThat(saved.getMember().getId()).isEqualTo(alice.id());
        assertThat(saved.ownedBy(alice.id())).isTrue();
        assertThat(saved.ownedBy(bob.id())).isFalse();
    }

    @Test
    void my_list_shows_only_my_warehouses() {
        warehouseService.create(warehouse(), bob);

        assertThat(warehouseService.list(alice)).hasSize(1);
        assertThat(warehouseService.list(bob)).hasSize(1);
    }

    /** 핵심 — 남의 창고는 403 이 아니라 404 다. */
    @Test
    void someone_elses_warehouse_looks_missing() {
        assertThatThrownBy(() -> warehouseService.get(aliceWarehouseId, bob))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.WAREHOUSE_NOT_FOUND);
    }

    @Test
    void the_owner_can_read_it() {
        assertThat(warehouseService.get(aliceWarehouseId, alice).warehouseId()).isEqualTo(aliceWarehouseId);
    }

    /** 관리자는 전체를 본다 — 영업이 고객사 현황을 봐야 한다. */
    @Test
    void an_admin_sees_everything() {
        var admin = new AuthenticatedMember(bob.id(), "ADMIN");

        assertThat(warehouseService.get(aliceWarehouseId, admin).warehouseId()).isEqualTo(aliceWarehouseId);
        assertThat(warehouseService.list(admin)).hasSize(1);
    }
}
