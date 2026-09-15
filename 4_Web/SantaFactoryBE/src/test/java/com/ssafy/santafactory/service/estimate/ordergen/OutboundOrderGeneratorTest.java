package com.ssafy.santafactory.service.estimate.ordergen;

import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.entity.store.Product;
import com.ssafy.santafactory.entity.store.Store;
import com.ssafy.santafactory.entity.warehouse.Rack;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.repository.ProductRepository;
import com.ssafy.santafactory.service.estimate.EstimateProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class OutboundOrderGeneratorTest {

    @Mock
    ProductRepository productRepository;
    @Mock
    OrderRuleProfileLoader profileLoader;
    @Mock
    Warehouse warehouse;

    /** 창고 시드(품고)와 같은 출고 시간대. horizon(6h)이 창(5h)보다 넓어 재매핑된 주문이 전부 살아남는다. */
    private static final long HORIZON_S = 6 * 3600L;

    private OutboundOrderGenerator generator;

    @BeforeEach
    void setUp() {
        generator = new OutboundOrderGenerator(productRepository, profileLoader, props(10));
        OrderRuleProfile profile = tinyProfile();
        List<Product> products = fakeProducts();
        when(profileLoader.getProfile()).thenReturn(profile);
        when(productRepository.findAllWithStoreAndRack()).thenReturn(products);
        when(warehouse.getOutboundStart()).thenReturn(LocalDateTime.of(2026, 1, 1, 13, 0));
        when(warehouse.getOutboundEnd()).thenReturn(LocalDateTime.of(2026, 1, 1, 18, 0));
    }

    @Test
    void same_seed_produces_identical_orders() {
        List<SimulationRequest.Outbound> first = generator.generate(warehouse, HORIZON_S, 30, 101L);
        List<SimulationRequest.Outbound> second = generator.generate(warehouse, HORIZON_S, 30, 101L);

        assertThat(second).isEqualTo(first);
    }

    @Test
    void different_seed_can_produce_different_orders() {
        List<SimulationRequest.Outbound> a = generator.generate(warehouse, HORIZON_S, 30, 101L);
        List<SimulationRequest.Outbound> b = generator.generate(warehouse, HORIZON_S, 30, 202L);

        assertThat(a).isNotEqualTo(b);
    }

    @Test
    void every_line_uses_a_real_rack_field() {
        List<SimulationRequest.Outbound> orders = generator.generate(warehouse, HORIZON_S, 30, 101L);

        assertThat(orders).isNotEmpty();
        assertThat(orders)
                .flatExtracting(SimulationRequest.Outbound::lines)
                .extracting(SimulationRequest.Line::rackId)
                .allMatch(rackId -> rackId.equals("A1") || rackId.equals("A2"));
    }

    @Test
    void orders_land_inside_the_horizon_window_sorted_with_sequential_ids() {
        List<SimulationRequest.Outbound> orders = generator.generate(warehouse, HORIZON_S, 30, 101L);

        assertThat(orders).isSortedAccordingTo((a, b) -> Long.compare(a.orderedAtS(), b.orderedAtS()));
        for (int i = 0; i < orders.size(); i++) {
            assertThat(orders.get(i).orderId()).isEqualTo(i + 1L);
        }
    }

    /**
     * 하루 전체([0,86400)) 시각으로 생성된 주문이 실제 출고 시간대(13~18시)로 재매핑돼 horizon(6h) 안에
     * 들어오는지 확인한다 — 이걸 빠뜨리면 DES가 horizon 밖 주문을 전부 버려 견적이 ALL_FAILED로 끝난다.
     */
    @Test
    void every_order_falls_inside_the_horizon_after_rescaling() {
        List<SimulationRequest.Outbound> orders = generator.generate(warehouse, HORIZON_S, 30, 101L);

        assertThat(orders).hasSize(30);
        assertThat(orders).allSatisfy(o -> assertThat(o.orderedAtS()).isBetween(0L, HORIZON_S - 1));
    }

    /**
     * 출고 종료 시각이 없으면 하루치 분포를 실행 창 [start, start+horizon) 으로 눌러 넣는다. 이걸 빼먹으면
     * 참조 분포에서 그 시간대에 원래 있던 몫(07시 시작이면 73 %)만 남고 나머지는 잘려 나가
     * 처리율·필요 대수가 그만큼 낙관적으로 나온다 (S15P21A106-214).
     */
    @Test
    void rescales_the_whole_day_into_the_horizon_when_outbound_end_is_missing() {
        when(warehouse.getOutboundEnd()).thenReturn(null);

        List<SimulationRequest.Outbound> orders = generator.generate(warehouse, HORIZON_S, 30, 101L);

        assertThat(orders).hasSize(30);
        assertThat(orders).allSatisfy(o -> assertThat(o.orderedAtS()).isBetween(0L, HORIZON_S - 1));
    }

    /** 자정을 넘는 교대(22~02시)는 종료가 시작보다 앞이라 같은 결함을 탄다 — 남은 하루 [22:00, 24:00) 에 넣는다. */
    @Test
    void rescales_an_overnight_window_into_the_remaining_day() {
        when(warehouse.getOutboundStart()).thenReturn(LocalDateTime.of(2026, 1, 1, 22, 0));
        when(warehouse.getOutboundEnd()).thenReturn(LocalDateTime.of(2026, 1, 2, 2, 0));

        List<SimulationRequest.Outbound> orders = generator.generate(warehouse, HORIZON_S, 30, 101L);

        assertThat(orders).hasSize(30);
        assertThat(orders).allSatisfy(o -> assertThat(o.orderedAtS()).isBetween(0L, 2 * 3600L - 1));
    }

    // ── 주문 크기 상한 24토트 (S15P21A106-214) ───────────────────────────────

    /**
     * 참조 데이터의 수량 꼬리(한 줄 1,000·2,400개)가 섞이면 시뮬이 --max-order-totes 24 로 그 주문을 빼 버려
     * 백엔드가 저장한 목록과 시뮬이 돈 목록이 어긋난다. 초과 주문은 수량만 다시 뽑아 상한 안에 넣는다.
     */
    @Test
    void no_order_exceeds_the_tote_cap() {
        generator = new OutboundOrderGenerator(productRepository, profileLoader, props(300));   // 줄 상한을 열어 꼬리를 살린다
        when(profileLoader.getProfile()).thenReturn(profileWithQuantities(new int[]{1, 200}, new double[]{1, 1}));   // 200개 = 25토트

        List<SimulationRequest.Outbound> orders = generator.generate(warehouse, HORIZON_S, 30, 101L);

        assertThat(orders).hasSize(30);
        assertThat(orders).allSatisfy(o -> assertThat(OutboundOrderGenerator.orderTotes(o.lines(), 8)).isLessThanOrEqualTo(24));
    }

    // ── 개인 구매 상한: 한 줄 수량 ≤ maxLineQty (S15P21A106-146) ─────────────

    /** 200개짜리 줄이 프로파일에 있어도 재추첨이 아니라 애초에 추첨 대상에서 빠진다. */
    @Test
    void no_line_exceeds_the_personal_purchase_cap() {
        when(profileLoader.getProfile()).thenReturn(profileWithQuantities(new int[]{1, 12, 200}, new double[]{1, 1, 1}));

        List<SimulationRequest.Outbound> orders = generator.generate(warehouse, HORIZON_S, 30, 101L);

        assertThat(orders).flatExtracting(SimulationRequest.Outbound::lines)
                .extracting(SimulationRequest.Line::qty)
                .allMatch(qty -> qty <= 10);
    }

    /**
     * 실제 프로파일(order_rules.json) 회귀: 상한 10 이면 줄 수량 최대 10, 남는 분포의 평균은 2.13 (상한 없이 3.52).
     * 상한값 10 이 실제로 나오는지도 본다 — 경계를 &lt; 로 잘못 쓰면 평균 구간만으로는 못 잡는다.
     * 한 줄이 최대 2토트라 24토트 안전핀은 발동하지 않는다.
     */
    @Test
    void shipped_profile_under_the_cap_yields_personal_sized_lines() {
        when(profileLoader.getProfile()).thenReturn(new OrderRuleProfileLoader(new ObjectMapper()).getProfile());

        List<SimulationRequest.Outbound> orders = generator.generate(warehouse, HORIZON_S, 2000, 101L);

        List<Integer> quantities = orders.stream().flatMap(o -> o.lines().stream()).map(SimulationRequest.Line::qty).toList();
        assertThat(quantities).allMatch(qty -> qty >= 1 && qty <= 10);
        assertThat(quantities).contains(10);                                  // 상한값 자체는 뽑힌다 (< 가 아니라 <=)
        double mean = quantities.stream().mapToInt(Integer::intValue).average().orElseThrow();
        assertThat(mean).isBetween(2.0, 2.3);                                 // 기대 2.13, 시드 고정이라 결정적
        assertThat(orders).allSatisfy(o -> assertThat(OutboundOrderGenerator.orderTotes(o.lines(), 8)).isLessThanOrEqualTo(24));
    }

    /**
     * 공용 픽스처(상품 8개·매장 2곳)를 일부만 읽는 테스트 — orderTotes 단위 테스트는 생성기를 안 부르고,
     * 상한 실패 테스트는 첫 주문에서 던진다. 이 둘만 stub 미사용 검사를 끈다(바깥 테스트는 strict 유지).
     */
    @Nested
    @MockitoSettings(strictness = Strictness.LENIENT)
    class PartialFixtureUse {

        /** 시뮬과 같은 셈: 같은 랙 수량을 합쳐 ceil(합 / toteUnits) 을 랙별로 더한다. */
        @Test
        void orderTotes_sums_ceil_of_quantity_per_rack() {
            List<SimulationRequest.Line> lines = List.of(
                    new SimulationRequest.Line(1L, "A1", 5),
                    new SimulationRequest.Line(2L, "A1", 4),     // A1 합 9 → 2토트
                    new SimulationRequest.Line(5L, "A2", 1));    // A2 1 → 1토트

            assertThat(OutboundOrderGenerator.orderTotes(lines, 8)).isEqualTo(3);
        }

        /** 어떤 수량을 뽑아도 상한을 못 맞추면 무한히 돌지 않고 실패한다 (파이썬 구현과 같은 1,000회 한도). */
        @Test
        void fails_when_no_quantity_draw_fits_the_cap() {
            generator = new OutboundOrderGenerator(productRepository, profileLoader, props(300));   // 줄 상한을 열어 꼬리를 살린다
            when(profileLoader.getProfile()).thenReturn(profileWithQuantities(new int[]{300}, new double[]{1}));   // 38토트

            assertThatThrownBy(() -> generator.generate(warehouse, HORIZON_S, 5, 101L))
                    .isInstanceOf(IllegalStateException.class)
                    .hasMessageContaining("24");
        }

        /** 참조 통계표는 12 에서 다스 봉우리가 서는 도매 꼬리를 품고 있다 — 상한 위 값은 추첨 대상에서 아예 뺀다. 상한값 자체는 남는다. */
        @Test
        void capQuantities_drops_values_above_the_cap_and_keeps_weights() {
            OrderRuleProfile.Histogram capped = OutboundOrderGenerator.capQuantities(
                    new OrderRuleProfile.Histogram(new int[]{1, 2, 10, 12, 24}, new double[]{5, 3, 4, 2, 1}), 10);

            assertThat(capped.values()).containsExactly(1, 2, 10);
            assertThat(capped.weights()).containsExactly(5.0, 3.0, 4.0);
        }

        /** 잘못된 상한은 첫 견적이 아니라 부팅 때 걸린다. */
        @Test
        void startup_validation_rejects_a_cap_below_every_profile_value() {
            when(profileLoader.getProfile()).thenReturn(profileWithQuantities(new int[]{12, 24}, new double[]{2, 1}));

            assertThatThrownBy(() -> generator.validateLineQtyCap())
                    .isInstanceOf(IllegalStateException.class)
                    .hasMessageContaining("max-line-qty=10");
        }

        /** 상한 아래 값이 하나도 없으면 설정 오류 — 조용히 넘기지 않는다. */
        @Test
        void capQuantities_fails_when_nothing_remains_below_the_cap() {
            OrderRuleProfile.Histogram tail = new OrderRuleProfile.Histogram(new int[]{12, 24}, new double[]{2, 1});

            assertThatThrownBy(() -> OutboundOrderGenerator.capQuantities(tail, 10))
                    .isInstanceOf(IllegalStateException.class)
                    .hasMessageContaining("10");
        }
    }

    private OrderRuleProfile profileWithQuantities(int[] values, double[] weights) {
        int[] minuteWeights = new int[1440];
        Arrays.fill(minuteWeights, 1);
        return new OrderRuleProfile(
                new OrderRuleProfile.Histogram(new int[]{1, 2, 3}, new double[]{3, 2, 1}),
                new OrderRuleProfile.Histogram(values, weights),
                minuteWeights,
                new double[][]{{0.0, 0.0}, {1.0, 1.0}});
    }

    /** 견적 설정 — 여기서 쓰는 건 한 줄 수량 상한(maxLineQty)뿐이다. */
    private static EstimateProperties props(int maxLineQty) {
        return new EstimateProperties(0L, 0L, 0L, 28, 6, 4, 1, Duration.ofMinutes(30), Duration.ofHours(6), "out", false,
                Duration.ofMinutes(10), maxLineQty);
    }

    private OrderRuleProfile tinyProfile() {
        int[] minuteWeights = new int[1440];
        Arrays.fill(minuteWeights, 1);
        return new OrderRuleProfile(
                new OrderRuleProfile.Histogram(new int[]{1, 2, 3}, new double[]{3, 2, 1}),
                new OrderRuleProfile.Histogram(new int[]{1, 2, 3}, new double[]{3, 2, 1}),
                minuteWeights,
                new double[][]{{0.0, 0.0}, {1.0, 1.0}});
    }

    /** 매장 2곳(A1/A2 랙), 상품 8개 — 생성 알고리즘이 매장 비중·랙 참조를 정상적으로 타는지 확인할 최소 구성. */
    private List<Product> fakeProducts() {
        Store storeA = mock(Store.class);
        when(storeA.getId()).thenReturn(10L);
        when(storeA.getOutboundCount()).thenReturn(500L);
        Store storeB = mock(Store.class);
        when(storeB.getId()).thenReturn(20L);
        when(storeB.getOutboundCount()).thenReturn(300L);

        Rack rackA = mock(Rack.class);
        when(rackA.getField()).thenReturn("A1");
        Rack rackB = mock(Rack.class);
        when(rackB.getField()).thenReturn("A2");

        List<Product> products = new ArrayList<>();
        for (long id = 1; id <= 8; id++) {
            Product product = mock(Product.class);
            when(product.getId()).thenReturn(id);
            when(product.getStore()).thenReturn(id <= 4 ? storeA : storeB);
            when(product.getRack()).thenReturn(id <= 4 ? rackA : rackB);
            products.add(product);
        }
        return products;
    }
}
