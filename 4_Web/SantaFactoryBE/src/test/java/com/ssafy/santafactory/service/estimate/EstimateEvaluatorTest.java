package com.ssafy.santafactory.service.estimate;

import org.junit.jupiter.api.Test;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 판정 로직 테스트.
 *
 * <p>KPI 는 지어내지 않고 B트랙 실측 스윕(3_FMS/sim_engine/results/b0z_sweep.csv)을 쓴다.
 * 헤딩 모델·시드 42 계열은 8대부터 처리율이 85 % 근처에서 포화하고 가동률은 계속 떨어지는데,
 * 이 "처리율은 더 안 오르고 가동률만 떨어지는" 구간이 손으로 만든 데이터에는 잘 안 나온다.
 *
 * <pre>
 *   대수      2     3     4     6     8    10    12    16
 *   처리율% 27.6  41.1  51.9  70.1  85.6  85.1  84.9  85.3
 *   가동률% 98.7  97.3  95.6  93.4  89.8  81.2  72.6  60.5
 * </pre>
 */
class EstimateEvaluatorTest {

    private static final String FIXTURE = "/fixture/b0z_sweep.csv";

    /**
     * 픽스처의 주문 도착 간격(틱). b0z 스윕은 {@code --order-gap} 기본값으로 돌렸다.
     * 1틱 = 1초이므로 수요는 3600/50 = 72 주문/시간.
     */
    private static final double ORDER_GAP_TICKS = 50.0;
    private static final double DEMAND_PER_HOUR = 3600.0 / ORDER_GAP_TICKS;

    /** 단가 1,500만 · 대당 구축·설치비 50만 (robots 시드) · 충전기 500만(미정이라 테스트 가정). */
    private static final EstimateProperties PROPS =
            new EstimateProperties(15_000_000L, 5_000_000L, 500_000L, 8, 6, 4, 1);

    private final CostCalculator costCalculator = new CostCalculator(PROPS);
    private final EstimateEvaluator evaluator = new EstimateEvaluator();

    private final List<RunResult> runs = loadHeadingSeed42();

    @Test
    void recommends_smallest_fleet_meeting_all_three_conditions() {
        // 6대: 처리율 70.1 % · 가동률 93.4 % · 1.03억 — 4대는 처리율 51.9 % 로 모자란다
        EstimateGoal goal = new EstimateGoal(70.0, 90.0, 1_000_000_000L);

        EstimateVerdict verdict = evaluator.evaluate(runs, goal);

        assertThat(verdict.recommendedCount()).isEqualTo(6);
        assertThat(verdict.reasonCode()).isNull();
    }

    @Test
    void marks_knee_where_throughput_saturates() {
        EstimateVerdict verdict = evaluator.evaluate(runs, new EstimateGoal(70.0, 90.0, 1_000_000_000L));

        // 8대 이후로는 대수를 늘려도 처리율이 85 % 에서 더 오르지 않는다
        assertThat(verdict.kneeCount()).isEqualTo(8);
    }

    @Test
    void reports_budget_exceeded_when_every_fleet_costs_too_much() {
        EstimateGoal goal = new EstimateGoal(20.0, 50.0, 30_000_000L);   // 최소 구성(2대)도 3,600만

        EstimateVerdict verdict = evaluator.evaluate(runs, goal);

        assertThat(verdict.recommendedCount()).isNull();
        assertThat(verdict.reasonCode()).isEqualTo(ReasonCode.BUDGET_EXCEEDED);
    }

    @Test
    void seeded_warehouse_target_of_95_percent_is_unreachable_within_eight_amrs() {
        // 창고 시드 값 그대로: 목표 처리율 95 % · 가동률 80 % · 예산 3억.
        // 8대까지의 최대 처리율이 85.6 % 라 어느 대수로도 못 채운다.
        EstimateGoal goal = new EstimateGoal(95.0, 80.0, 300_000_000L);

        EstimateVerdict verdict = evaluator.evaluate(runs, goal);

        assertThat(verdict.recommendedCount()).isNull();
        assertThat(verdict.reasonCode()).isEqualTo(ReasonCode.THROUGHPUT_SHORT);
        assertThat(verdict.kneeCount()).isEqualTo(8);   // 대수를 더 늘려도 소용없다는 근거
    }

    @Test
    void reports_utilization_short_when_the_fast_enough_fleet_idles_too_much() {
        // 처리율 85 % 는 8대 이상이라야 되는데, 8대 가동률은 89.8 % 로 95 % 에 못 미친다
        EstimateGoal goal = new EstimateGoal(85.0, 95.0, 10_000_000_000L);

        EstimateVerdict verdict = evaluator.evaluate(runs, goal);

        assertThat(verdict.recommendedCount()).isNull();
        assertThat(verdict.reasonCode()).isEqualTo(ReasonCode.UTILIZATION_SHORT);
    }

    @Test
    void reports_all_failed_when_no_run_produced_a_result() {
        EstimateVerdict verdict = evaluator.evaluate(List.of(), new EstimateGoal(70.0, 90.0, 1_000_000_000L));

        assertThat(verdict.recommendedCount()).isNull();
        assertThat(verdict.kneeCount()).isNull();
        assertThat(verdict.reasonCode()).isEqualTo(ReasonCode.ALL_FAILED);
    }

    @Test
    void treats_null_input_as_all_failed() {
        EstimateVerdict verdict = evaluator.evaluate(null, new EstimateGoal(70.0, 90.0, 1_000_000_000L));

        assertThat(verdict.reasonCode()).isEqualTo(ReasonCode.ALL_FAILED);
    }

    @Test
    void evaluates_the_surviving_runs_when_some_fleets_failed() {
        List<RunResult> partial = runs.stream()
                .filter(run -> List.of(2, 3, 8, 16).contains(run.amrCount()))
                .toList();

        EstimateVerdict verdict = evaluator.evaluate(partial, new EstimateGoal(70.0, 80.0, 1_000_000_000L));

        assertThat(verdict.recommendedCount()).isEqualTo(8);   // 4·6대가 없으니 8대가 최소
    }

    @Test
    void skips_knee_detection_with_two_or_fewer_points() {
        List<RunResult> twoPoints = runs.subList(0, 2);

        EstimateVerdict verdict = evaluator.evaluate(twoPoints, new EstimateGoal(20.0, 90.0, 1_000_000_000L));

        assertThat(verdict.kneeCount()).isNull();
        assertThat(verdict.recommendedCount()).isEqualTo(2);
    }

    @Test
    void sorts_by_fleet_size_regardless_of_input_order() {
        List<RunResult> shuffled = new ArrayList<>(runs);
        Collections.reverse(shuffled);

        EstimateVerdict verdict = evaluator.evaluate(shuffled, new EstimateGoal(70.0, 90.0, 1_000_000_000L));

        assertThat(verdict.recommendedCount()).isEqualTo(6);
        assertThat(verdict.kneeCount()).isEqualTo(8);
    }

    // ── 픽스처 ────────────────────────────────────────────────────────────────

    /**
     * b0z 스윕에서 헤딩 모델·시드 42 행만 골라 RunResult 로 만든다.
     *
     * <p>b0z 는 <b>유한 주문 모드</b>(40주문을 다 처리하고 종료)라 완료율이 모든 대수에서 100 % 다.
     * 그래서 처리율을 CSV 에서 그대로 읽을 수 없고, <b>수요 대비 처리 능력</b>으로 환산한다:
     * {@code orders_per_h / 72 × 100}. 8대에서 포화하는 곡선 모양은 그대로 보존된다.
     * (완료율을 직접 재려면 고정 시간 모드 {@code --horizon} 스윕 CSV 가 필요하다 — 아직 없다.)
     */
    private List<RunResult> loadHeadingSeed42() {
        List<RunResult> loaded = new ArrayList<>();
        try (InputStream in = getClass().getResourceAsStream(FIXTURE)) {
            assertThat(in).as("fixture %s must exist in test/resources", FIXTURE).isNotNull();
            BufferedReader reader = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8));

            Map<String, Integer> col = headerIndex(reader.readLine());
            String line;
            while ((line = reader.readLine()) != null) {
                String[] f = line.split(",", -1);
                if (!"heading".equals(f[col.get("engine")]) || !"42".equals(f[col.get("seed")])) {
                    continue;
                }
                int amrCount = Integer.parseInt(f[col.get("n_robots")]);
                double ordersPerHour = Double.parseDouble(f[col.get("orders_per_h")]);
                double utilIncludingService = Double.parseDouble(f[col.get("util_incl_service")]);
                loaded.add(new RunResult(
                        amrCount,
                        Math.min(100.0, ordersPerHour / DEMAND_PER_HOUR * 100.0),
                        utilIncludingService * 100.0,
                        costCalculator.cost(amrCount)));
            }
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
        loaded.sort(Comparator.comparingInt(RunResult::amrCount));
        assertThat(loaded).as("heading rows with seed 42").isNotEmpty();
        return loaded;
    }

    private Map<String, Integer> headerIndex(String header) {
        String[] names = header.split(",", -1);
        Map<String, Integer> index = new HashMap<>();
        for (int i = 0; i < names.length; i++) {
            index.put(names[i], i);
        }
        return index;
    }
}
