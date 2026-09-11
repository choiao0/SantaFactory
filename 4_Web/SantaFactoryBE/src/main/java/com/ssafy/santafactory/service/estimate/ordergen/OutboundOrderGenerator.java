package com.ssafy.santafactory.service.estimate.ordergen;

import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.entity.store.Product;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.repository.ProductRepository;
import lombok.RequiredArgsConstructor;
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
 * 출고 주문을 자체 생성한다 — {@code 3_FMS/order_gen/generate_orders.py}의 가중 추첨 알고리즘을
 * Java로 옮긴 것이다(파이썬 RNG와 비트 단위로 같을 필요는 없음, seed별 내부 재현성만 보장).
 *
 * <p>창고별로 다른 상품 마스터를 쓰지 않는다 — 물리 레이아웃(zone·store·rack·product)은 창고마다
 * 있는 게 아니라 앱 전체에 하나뿐인 고정 데이터라({@code ProductRepository}), 견적이 어느 창고
 * 것이든 같은 마스터에서 뽑는다(파이썬 워커도 항상 같은 마스터 파일을 썼다).
 *
 * <p>상품 인기도(popularity)는 {@code order_rules.json}의 누적곡선을, 매장 가중치(store factor)는
 * {@code Store.outboundCount}를 쓴다. ABC 등급은 원본에서도 진단용일 뿐 추첨에 안 쓰여 포팅하지 않는다.
 *
 * <p>생성 직후 시각은 하루 전체([0, 86400)초, 프로파일의 참조 창고 분포)다. DES는 {@code ordered_at_s}를
 * horizon 시작 기준 상대 초로 읽어 horizon 밖은 버리므로, 그대로 보내면 대부분 버려진다(파이썬 쪽
 * {@code slice_orders.rescale_orders}/{@code slice_orders}와 정확히 같은 문제) — 그래서 창고의 실제
 * 출고 시간대로 밀도를 재매핑(rescale)한 뒤, horizon 기준으로 자르고 시각을 0부터 다시 매긴다(slice).
 */
@Service
@RequiredArgsConstructor
public class OutboundOrderGenerator {

    private final ProductRepository productRepository;
    private final OrderRuleProfileLoader profileLoader;

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
        List<Integer> qtyValues = box(profile.quantity().values());
        List<Double> qtyWeights = box(profile.quantity().weights());
        List<Integer> minuteIndices = IntStream.range(0, 1440).boxed().toList();
        List<Double> minuteWeights = java.util.Arrays.stream(profile.minuteWeights()).asDoubleStream().boxed().toList();

        record Draft(int sequence, long orderedAtS, List<SimulationRequest.Line> lines) {
        }

        List<Draft> drafts = new ArrayList<>(orderCount);
        for (int sequence = 0; sequence < orderCount; sequence++) {
            int originalK = weightedChoice(contentRng, lineValues, lineWeights);
            Product first = weightedChoice(contentRng, sortedProducts, globalWeights);
            List<Product> candidates = productsByStore.get(first.getStore().getId());
            int effectiveK = Math.min(originalK, candidates.size());

            List<Product> selected = new ArrayList<>();
            selected.add(first);
            List<Product> remaining = new ArrayList<>(candidates);
            remaining.remove(first);
            while (selected.size() < effectiveK) {
                List<Double> weights = remaining.stream().map(p -> popularity.get(p.getId())).toList();
                Product choice = weightedChoice(contentRng, remaining, weights);
                selected.add(choice);
                remaining.remove(choice);
            }

            List<SimulationRequest.Line> lines = selected.stream()
                    .sorted(Comparator.comparing(Product::getId))
                    .map(p -> new SimulationRequest.Line(p.getId(), p.getRack().getField(),
                            weightedChoice(contentRng, qtyValues, qtyWeights)))
                    .toList();

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

        long startS = secondOfDay(warehouse.getOutboundStart());
        long endS = warehouse.getOutboundEnd() != null ? secondOfDay(warehouse.getOutboundEnd()) : 0;
        return sliceToWindow(startS < endS ? rescale(outbound, startS, endS) : outbound, startS, horizonSeconds);
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
        long end = Math.min(start + horizonSeconds, 86400);
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
