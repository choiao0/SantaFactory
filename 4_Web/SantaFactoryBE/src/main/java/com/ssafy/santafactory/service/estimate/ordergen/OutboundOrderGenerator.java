package com.ssafy.santafactory.service.estimate.ordergen;

import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.entity.store.Product;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.repository.ProductRepository;
import com.ssafy.santafactory.service.estimate.EstimateProperties;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.stream.Collectors;
import java.util.stream.IntStream;

/**
 * 출고 주문을 자체 생성한다 — 3_FMS 의 {@code order_gen/generate_orders.py}(S15P21A106-212 로 삭제, 마지막 판은
 * 커밋 7cd68ce)의 가중 추첨 알고리즘을 Java로 옮긴 것이다(파이썬 RNG와 비트 단위로 같을 필요는 없음, seed별 내부 재현성만 보장).
 *
 * <p>창고별로 다른 상품 마스터를 쓰지 않는다 — 물리 레이아웃(zone·store·rack·product)은 창고마다
 * 있는 게 아니라 앱 전체에 하나뿐인 고정 데이터라({@code ProductRepository}), 견적이 어느 창고
 * 것이든 같은 마스터에서 뽑는다(파이썬 워커도 항상 같은 마스터 파일을 썼다).
 *
 * <p>상품 인기도(popularity)는 {@code order_rules.json}의 누적곡선을, 매장 가중치(store factor)는
 * {@code Store.outboundCount}를 쓴다. ABC 등급은 원본에서도 진단용일 뿐 추첨에 안 쓰여 포팅하지 않는다.
 *
 * <p>개인 소비자 창고 전제(S15P21A106-146): 한 줄 수량은 {@code estimate.max-line-qty}(기본 10) 아래만 뽑는다 —
 * 참조 통계표의 도매 꼬리를 추첨 대상에서 아예 뺀다({@link #capQuantities}).
 *
 * <p>그 위에 <b>주문 하나의 수량 합</b> 상한이 있다({@code estimate.max-order-qty}, 기본 10 — 시나리오 결정
 * 2026-09-15 "개인 주문은 수량 합 10개 이하"). 넘으면 <b>주문을 통째로 다시 뽑는다</b> — 줄 수부터 다시
 * 뽑는다는 뜻이다 (S15P21A106-232).
 *
 * <p>수량만 다시 뽑아도 지금 상품 마스터에서는 상한을 맞출 수 있다 — 주문은 한 매장 안에서만 뽑고
 * 매장당 상품이 6개뿐이라 줄 수가 6에서 잘리기 때문이다. 그래도 주문 전체를 다시 뽑는 이유는 둘이다:
 * (1) 수량만 다시 뽑으면 줄 수 분포가 그대로 남아 FMS 기준선의 주문 분포와 어긋난다, (2) 매장당 상품이
 * 상한보다 많아지면 줄 수가 많은 주문은 각 줄 최소 1개만으로도 합이 상한을 넘어 영원히 빠져나오지 못한다.
 *
 * <p>이 상한은 FMS 가 six 기준선·θ 를 뽑을 때 쓴 주문 규칙과 같다. 백엔드가 다른 규칙으로 주문을 만들면
 * 같은 시뮬 코드인데도 견적이 기준선과 다른 주문 분포 위에서 나와 처리량·리드타임이 어긋난다.
 *
 * <p>생성 직후 시각은 하루 전체([0, 86400)초, 프로파일의 참조 창고 분포)다. DES는 {@code ordered_at_s}를
 * horizon 시작 기준 상대 초로 읽어 horizon 밖은 버리므로, 그대로 보내면 대부분 버려진다(파이썬 쪽
 * {@code slice_orders.rescale_orders}/{@code slice_orders}와 정확히 같은 문제) — 그래서 창고의 실제
 * 출고 시간대로 밀도를 재매핑(rescale)한 뒤, horizon 기준으로 자르고 시각을 0부터 다시 매긴다(slice).
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OutboundOrderGenerator {

    private static final long SECONDS_PER_DAY = 86_400L;
    /** 상한을 넘는 주문의 재추첨 한도 — 파이썬 원본과 같은 값. */
    private static final int MAX_CAP_ATTEMPTS = 1_000;

    private final ProductRepository productRepository;
    private final OrderRuleProfileLoader profileLoader;
    private final EstimateProperties properties;

    /** 상한 설정 오류(상한 이하 수량 값 없음)는 첫 견적 요청의 500 이 아니라 부팅 실패로 드러나게 한다. */
    @PostConstruct
    void validateQtyCaps() {
        OrderRuleProfile.Histogram capped = capQuantities(profileLoader.getProfile().quantity(), properties.maxLineQty());
        // 가장 작은 수량조차 주문 상한을 넘으면 1줄 주문도 못 만든다 — 재추첨이 1,000회 돌고 죽는다
        int minQty = java.util.Arrays.stream(capped.values()).min().orElseThrow();
        if (properties.maxOrderQty() < minQty) {
            throw new IllegalStateException(String.format(
                    "estimate.max-order-qty=%d 가 프로파일 최소 수량 %d 보다 작아 주문을 만들 수 없음",
                    properties.maxOrderQty(), minQty));
        }
    }

    public List<SimulationRequest.Outbound> generate(Warehouse warehouse, long horizonSeconds, int orderCount, long seed) {
        List<Product> products = productRepository.findAllWithStoreAndRack();
        if (products.isEmpty()) {
            throw new IllegalStateException("상품 마스터데이터가 없어 주문을 생성할 수 없음");
        }
        OrderRuleProfile profile = profileLoader.getProfile();

        Random contentRng = new Random(seed);
        Random releaseRng = new Random(seed + 1);

        Map<Long, List<Product>> productsByStore = products.stream()
                .collect(Collectors.groupingBy(p -> p.getStore().getId()));
        productsByStore.values().forEach(list -> list.sort(Comparator.comparing(Product::getId)));

        Map<Long, Double> popularity = popularity(products, profile.skuCumulative(), contentRng);
        Map<Long, Double> storeFactor = storeFactor(productsByStore);

        List<Product> sortedProducts = products.stream().sorted(Comparator.comparing(Product::getId)).toList();
        List<Double> globalWeights = sortedProducts.stream()
                .map(p -> popularity.get(p.getId()) * storeFactor.get(p.getStore().getId()))
                .toList();

        List<Integer> lineValues = box(profile.lineCount().values());
        List<Double> lineWeights = box(profile.lineCount().weights());
        OrderRuleProfile.Histogram quantity = capQuantities(profile.quantity(), properties.maxLineQty());
        List<Integer> qtyValues = box(quantity.values());
        List<Double> qtyWeights = box(quantity.weights());
        List<Integer> minuteIndices = IntStream.range(0, 1440).boxed().toList();
        List<Double> minuteWeights = java.util.Arrays.stream(profile.minuteWeights()).asDoubleStream().boxed().toList();

        record Draft(int sequence, long orderedAtS, List<SimulationRequest.Line> lines) {
        }

        List<Draft> drafts = new ArrayList<>(orderCount);
        int cappedOrders = 0;
        DrawContext ctx = new DrawContext(contentRng, lineValues, lineWeights, sortedProducts, globalWeights,
                productsByStore, popularity, qtyValues, qtyWeights);
        for (int sequence = 0; sequence < orderCount; sequence++) {
            LineDraw draw = drawWithinOrderQty(ctx, sequence);
            cappedOrders += draw.redraws() > 0 ? 1 : 0;
            List<SimulationRequest.Line> lines = draw.lines();

            int minute = weightedChoice(releaseRng, minuteIndices, minuteWeights);
            long orderedAtS = minute * 60L + releaseRng.nextInt(60);
            drafts.add(new Draft(sequence, orderedAtS, lines));
        }

        List<Draft> sorted = drafts.stream()
                .sorted(Comparator.comparingLong(Draft::orderedAtS).thenComparingInt(Draft::sequence))
                .toList();
        List<SimulationRequest.Outbound> outbound = new ArrayList<>(sorted.size());
        for (int i = 0; i < sorted.size(); i++) {
            Draft d = sorted.get(i);
            outbound.add(new SimulationRequest.Outbound((long) (i + 1), d.orderedAtS(), d.lines()));
        }

        List<SimulationRequest.Outbound> window = mapToOutboundWindow(warehouse, outbound, horizonSeconds);
        log.info("출고 주문 생성: 하루 {}건 중 실행 창 {}건 (seed {}), 수량 합 {} 상한 재추첨 {}건",
                orderCount, window.size(), seed, properties.maxOrderQty(), cappedOrders);
        return window;
    }

    /**
     * 한 줄 수량 히스토그램에서 {@code maxLineQty} 를 넘는 값을 뺀 사본 (S15P21A106-146). 참조 통계표(신발 물류센터
     * 피킹 로그)는 1~11 까지 매끈하게 줄다가 12 에서 다시 튀고 24·36·48·72 에 봉우리가 선다 — 다스·케이스로 사는
     * 도매 흔적이다. 개인은 온라인몰 1회 최대 구매 수량이 10 안팎이라 그 아래만 쓴다. 가중치는 다시 정규화하지
     * 않는다({@link #weightedChoice} 가 매번 남은 합으로 나눈다). 남는 값이 없으면 설정 오류로 바로 실패한다.
     */
    static OrderRuleProfile.Histogram capQuantities(OrderRuleProfile.Histogram quantity, int maxLineQty) {
        int[] values = quantity.values();
        double[] weights = quantity.weights();
        int kept = (int) java.util.Arrays.stream(values).filter(v -> v <= maxLineQty).count();
        if (maxLineQty < 1 || kept == 0) {
            throw new IllegalStateException(String.format(
                    "estimate.max-line-qty=%d 이하인 수량 값이 프로파일에 없음 (최소 %d)", maxLineQty, java.util.Arrays.stream(values).min().orElse(0)));
        }
        int[] cappedValues = new int[kept];
        double[] cappedWeights = new double[kept];
        for (int i = 0, j = 0; i < values.length; i++) {
            if (values[i] <= maxLineQty) {
                cappedValues[j] = values[i];
                cappedWeights[j] = weights[i];
                j++;
            }
        }
        return new OrderRuleProfile.Histogram(cappedValues, cappedWeights);
    }

    /** 한 주문의 라인과, 그걸 상한 안에 넣느라 수량을 다시 뽑은 횟수. */
    private record LineDraw(List<SimulationRequest.Line> lines, int redraws) {
    }

    /** 주문 하나를 뽑는 데 필요한 추첨 재료 — 인자 아홉 개를 메서드마다 끌고 다니지 않으려고 묶었다. */
    private record DrawContext(Random rng,
                               List<Integer> lineValues, List<Double> lineWeights,
                               List<Product> sortedProducts, List<Double> globalWeights,
                               Map<Long, List<Product>> productsByStore, Map<Long, Double> popularity,
                               List<Integer> qtyValues, List<Double> qtyWeights) {
    }

    /**
     * 수량 합이 {@code estimate.max-order-qty} 를 넘으면 <b>주문을 통째로 다시 뽑는다</b> (S15P21A106-232).
     *
     * <p>줄 수부터 다시 뽑는다. 줄 수가 상한보다 많은 주문은 각 줄 최소 1개만으로도 합이 상한을 넘어,
     * 수량만 다시 뽑아서는 영원히 빠져나오지 못하기 때문이다. 지금 상품 마스터(매장당 6개)에서는 줄 수가
     * 6에서 잘려 그 상황이 오지 않지만, 규칙 자체를 안전한 쪽으로 둔다.
     *
     * <p>1줄 주문이 72.7 % 이고 그 수량은 {@link #capQuantities} 가 이미 상한 아래로 잘라 두므로 한 번에
     * 성공하는 경우가 대부분이다 — 한도(1,000회)에 닿는 일은 없다시피 하다.
     */
    private LineDraw drawWithinOrderQty(DrawContext ctx, int sequence) {
        int maxOrderQty = properties.maxOrderQty();
        List<SimulationRequest.Line> lines = drawOrder(ctx);
        int redraws = 0;
        while (sumQty(lines) > maxOrderQty) {
            if (++redraws > MAX_CAP_ATTEMPTS) {
                throw new IllegalStateException(String.format(
                        "주문 %d: 수량 합 %d 이하인 주문을 %d회 재추첨으로 만들지 못함",
                        sequence, maxOrderQty, MAX_CAP_ATTEMPTS));
            }
            lines = drawOrder(ctx);
        }
        return new LineDraw(lines, redraws);
    }

    /** 줄 수 → 첫 상품 → 같은 매장에서 나머지 상품 → 줄마다 수량. 재추첨은 이 전체를 다시 돌린다. */
    private List<SimulationRequest.Line> drawOrder(DrawContext ctx) {
        int originalK = weightedChoice(ctx.rng(), ctx.lineValues(), ctx.lineWeights());
        Product first = weightedChoice(ctx.rng(), ctx.sortedProducts(), ctx.globalWeights());
        List<Product> candidates = ctx.productsByStore().get(first.getStore().getId());
        int effectiveK = Math.min(originalK, candidates.size());

        List<Product> selected = new ArrayList<>();
        selected.add(first);
        List<Product> remaining = new ArrayList<>(candidates);
        remaining.remove(first);
        while (selected.size() < effectiveK) {
            List<Double> weights = remaining.stream().map(p -> ctx.popularity().get(p.getId())).toList();
            Product choice = weightedChoice(ctx.rng(), remaining, weights);
            selected.add(choice);
            remaining.remove(choice);
        }

        return selected.stream()
                .sorted(Comparator.comparing(Product::getId))
                .map(p -> new SimulationRequest.Line(p.getId(), p.getRack().getField(),
                        weightedChoice(ctx.rng(), ctx.qtyValues(), ctx.qtyWeights())))
                .toList();
    }

    /** 주문 하나의 수량 합 — 토트 10개들이 기준으로 이 값이 곧 "주문 1건 = 토트 1개" 여부를 가른다. */
    static int sumQty(List<SimulationRequest.Line> lines) {
        return lines.stream().mapToInt(SimulationRequest.Line::qty).sum();
    }

    /**
     * 하루 시각 → 창고 출고 시간대 [start, end) 로 재매핑 → 실행 창 [start, start+horizon) 으로 자르기.
     *
     * <p>종료 시각이 없거나 시작보다 앞이면(자정을 넘는 교대) 실행 창 자체를 출고 시간대로 본다. 이 경우
     * 재매핑을 건너뛰면 참조 분포에서 그 시간대에 원래 있던 몫(07시 시작이면 73 %)만 남고 나머지 하루치는
     * 잘려 나가 처리율·필요 대수가 낙관적으로 나온다 (S15P21A106-214). 이 폴백 창은 24:00 에서 잘리므로
     * 자정을 넘는 교대는 남은 하루까지만 쓰고 그만큼 밀도가 높아진다 — 하루 경계를 넘겨 매핑하는 건 별도 판단.
     * 종료 시각이 있는 창은 그대로 [start, end) 에 눌러 넣으므로 start+horizon 이 자정을 넘어도 주문이 잘리지 않는다.
     */
    private List<SimulationRequest.Outbound> mapToOutboundWindow(
            Warehouse warehouse, List<SimulationRequest.Outbound> outbound, long horizonSeconds) {
        long startS = secondOfDay(warehouse.getOutboundStart());
        long endS = warehouse.getOutboundEnd() != null ? secondOfDay(warehouse.getOutboundEnd()) : 0;
        if (endS <= startS) {
            endS = Math.min(startS + horizonSeconds, SECONDS_PER_DAY);
        }
        return sliceToWindow(rescale(outbound, startS, endS), startS, horizonSeconds);
    }

    private long secondOfDay(LocalDateTime dateTime) {
        return dateTime.toLocalTime().toSecondOfDay();
    }

    /**
     * 하루 전체 시각 구간(첫 주문~마지막 주문+1초)을 [start, end)로 선형 비례 매핑한다
     * ({@code slice_orders.rescale_orders}와 동일) — 몰림 모양은 유지, 밀도만 실제 출고 시간대에 맞춘다.
     */
    private List<SimulationRequest.Outbound> rescale(List<SimulationRequest.Outbound> orders, long start, long end) {
        if (orders.isEmpty()) {
            return orders;
        }
        long lo = orders.stream().mapToLong(SimulationRequest.Outbound::orderedAtS).min().orElseThrow();
        long hi = orders.stream().mapToLong(SimulationRequest.Outbound::orderedAtS).max().orElseThrow() + 1;
        double scale = (double) (end - start) / (hi - lo);
        List<SimulationRequest.Outbound> moved = new ArrayList<>(orders.size());
        for (SimulationRequest.Outbound o : orders) {
            long movedAtS = start + (long) Math.floor((o.orderedAtS() - lo) * scale);
            moved.add(new SimulationRequest.Outbound(o.orderId(), movedAtS, o.lines()));
        }
        return moved;
    }

    /**
     * [start, start+horizon) 구간의 주문만 남기고 시각을 start 기준으로 다시 매긴다
     * ({@code slice_orders.slice_orders}와 동일). 걸러진 주문의 order_id는 그대로 둔다(다시 안 매김) —
     * 파이썬 쪽도 슬라이스 후 재번호를 매기지 않는다.
     */
    private List<SimulationRequest.Outbound> sliceToWindow(
            List<SimulationRequest.Outbound> orders, long start, long horizonSeconds) {
        long end = Math.min(start + horizonSeconds, SECONDS_PER_DAY);
        List<SimulationRequest.Outbound> kept = new ArrayList<>();
        for (SimulationRequest.Outbound o : orders) {
            if (o.orderedAtS() >= start && o.orderedAtS() < end) {
                kept.add(new SimulationRequest.Outbound(o.orderId(), o.orderedAtS() - start, o.lines()));
            }
        }
        return kept;
    }

    /** 순위(rank)를 섞어(shuffle) 누적곡선에 대응시켜, 상품별 인기 가중치를 산출한다. */
    private Map<Long, Double> popularity(List<Product> products, double[][] curve, Random contentRng) {
        List<Product> ranked = new ArrayList<>(products.stream().sorted(Comparator.comparing(Product::getId)).toList());
        java.util.Collections.shuffle(ranked, contentRng);
        int count = ranked.size();
        Map<Long, Double> popularity = new HashMap<>();
        double previous = 0.0;
        for (int i = 0; i < count; i++) {
            double cumulative = interpolate(curve, (double) (i + 1) / count);
            popularity.put(ranked.get(i).getId(), Math.max(0.0, cumulative - previous));
            previous = cumulative;
        }
        return popularity;
    }

    /** 매장별 outbound_count 비례 가중치. 전부 없으면 균등, 합이 0 이하면 균등으로 폴백한다. */
    private Map<Long, Double> storeFactor(Map<Long, List<Product>> productsByStore) {
        Map<Long, Long> outboundCounts = new HashMap<>();
        for (Map.Entry<Long, List<Product>> entry : productsByStore.entrySet()) {
            Long count = entry.getValue().get(0).getStore().getOutboundCount();
            outboundCounts.put(entry.getKey(), count == null ? 0L : count);
        }
        long total = outboundCounts.values().stream().mapToLong(Long::longValue).sum();
        Map<Long, Double> factor = new HashMap<>();
        if (total <= 0) {
            double uniform = 1.0 / outboundCounts.size();
            outboundCounts.keySet().forEach(id -> factor.put(id, uniform));
        } else {
            outboundCounts.forEach((id, count) -> factor.put(id, count / (double) total));
        }
        return factor;
    }

    /** 누적곡선(오름차순 [x,y] 점들)을 선형보간한다 — bisect_right 와 동일한 구간 탐색. */
    private double interpolate(double[][] points, double x) {
        int lo = 0;
        int hi = points.length;
        while (lo < hi) {
            int mid = (lo + hi) / 2;
            if (points[mid][0] <= x) {
                lo = mid + 1;
            } else {
                hi = mid;
            }
        }
        if (lo == 0) {
            return points[0][1];
        }
        if (lo == points.length) {
            return points[points.length - 1][1];
        }
        double x1 = points[lo - 1][0];
        double y1 = points[lo - 1][1];
        double x2 = points[lo][0];
        double y2 = points[lo][1];
        return y1 + (y2 - y1) * (x - x1) / (x2 - x1);
    }

    /** 누적 가중치 추첨. 부동소수점 오차로 끝까지 못 고르면 마지막 양의 가중치 값으로 폴백한다. */
    private <T> T weightedChoice(Random rng, List<T> values, List<Double> weights) {
        double total = weights.stream().mapToDouble(Double::doubleValue).sum();
        if (total <= 0) {
            return values.get(0);
        }
        double point = rng.nextDouble() * total;
        double cumulative = 0.0;
        T fallback = null;
        for (int i = 0; i < values.size(); i++) {
            double weight = weights.get(i);
            if (weight > 0) {
                fallback = values.get(i);
            }
            cumulative += weight;
            if (point < cumulative) {
                return values.get(i);
            }
        }
        return fallback != null ? fallback : values.get(0);
    }

    private List<Integer> box(int[] values) {
        return java.util.Arrays.stream(values).boxed().toList();
    }

    private List<Double> box(double[] values) {
        return java.util.Arrays.stream(values).boxed().toList();
    }
}
