package com.ssafy.santafactory.service.estimate.ordergen;

import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.entity.store.Product;
import com.ssafy.santafactory.entity.store.Store;
import com.ssafy.santafactory.entity.warehouse.Rack;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.repository.ProductRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
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
        generator = new OutboundOrderGenerator(productRepository, profileLoader);
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
