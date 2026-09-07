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
 * <p>KPI 는 지어내지 않고 B트랙 실측 스윕(3_FMS/sim_engine/results/b0z_sweep.csv)을 그대로 쓴다.
 * 헤딩 모델·시드 42 계열은 8대부터 처리량이 61 주문/h 근처에서 포화하고 가동률은 계속 떨어지는데,
 * 이 "처리량은 더 안 오르고 가동률만 떨어지는" 구간이 손으로 만든 데이터에는 잘 안 나온다.
 */
class EstimateEvaluatorTest {

    private static final String FIXTURE = "/fixture/b0z_sweep.csv";

    /** 단가는 미정이라 테스트에서만 쓰는 값. 대당 1억, 충전기 500만, 설치 3천만. */
    private static final EstimateProperties PROPS =
            new EstimateProperties(100_000_000L, 5_000_000L, 30_000_000L, 8, 6, 4, 1);

    private final CostCalculator costCalculator = new CostCalculator(PROPS);
    private final EstimateEvaluator evaluator = new EstimateEvaluator();

    /** 실측 곡선: 2대 19.9 → 6대 50.5 → 8대 61.6 주문/h, 이후 61 근처 포화. 가동률은 0.987 → 0.605. */
    private final List<RunResult> runs = loadHeadingSeed42();

    @Test
    void recommends_smallest_fleet_meeting_all_three_conditions() {
        // 6대: 50.5 주문/h · 가동률 0.934 · 6.4억 — 6대보다 적은 대수는 처리량이 모자란다
        EstimateGoal goal = new EstimateGoal(50.0, 0.9, 1_000_000_000L);

        EstimateVerdict verdict = evaluator.evaluate(runs, goal);

        assertThat(verdict.recommendedCount()).isEqualTo(6);
        assertThat(verdict.reasonCode()).isNull();
    }

    @Test
    void marks_knee_where_throughput_saturates() {
        EstimateVerdict verdict = evaluator.evaluate(runs, new EstimateGoal(50.0, 0.9, 1_000_000_000L));

        // 8대 이후로는 대수를 늘려도 61 주문/h 에서 더 오르지 않는다
        assertThat(verdict.kneeCount()).isEqualTo(8);
    }

    @Test
    void reports_budget_exceeded_when_every_fleet_costs_too_much() {
        EstimateGoal goal = new EstimateGoal(10.0, 0.5, 100_000_000L);   // 최소 구성도 2.35억

        EstimateVerdict verdict = evaluator.evaluate(runs, goal);

        assertThat(verdict.recommendedCount()).isNull();
        assertThat(verdict.reasonCode()).isEqualTo(ReasonCode.BUDGET_EXCEEDED);
    }

    @Test
    void reports_throughput_short_when_no_fleet_reaches_the_target() {
        EstimateGoal goal = new EstimateGoal(100.0, 0.5, 10_000_000_000L);   // 최대 61.6 주문/h

        EstimateVerdict verdict = evaluator.evaluate(runs, goal);

        assertThat(verdict.recommendedCount()).isNull();
        assertThat(verdict.reasonCode()).isEqualTo(ReasonCode.THROUGHPUT_SHORT);
    }

    @Test
    void reports_utilization_short_when_the_fast_enough_fleet_idles_too_much() {
        // 61 주문/h 는 8대 이상이라야 되는데, 8대 가동률은 0.898 로 0.95 에 못 미친다
        EstimateGoal goal = new EstimateGoal(61.0, 0.95, 10_000_000_000L);

        EstimateVerdict verdict = evaluator.evaluate(runs, goal);

        assertThat(verdict.recommendedCount()).isNull();
        assertThat(verdict.reasonCode()).isEqualTo(ReasonCode.UTILIZATION_SHORT);
    }

    @Test
    void reports_all_failed_when_no_run_produced_a_result() {
        EstimateVerdict verdict = evaluator.evaluate(List.of(), new EstimateGoal(50.0, 0.9, 1_000_000_000L));

        assertThat(verdict.recommendedCount()).isNull();
        assertThat(verdict.kneeCount()).isNull();
        assertThat(verdict.reasonCode()).isEqualTo(ReasonCode.ALL_FAILED);
    }

    @Test
    void treats_null_input_as_all_failed() {
        EstimateVerdict verdict = evaluator.evaluate(null, new EstimateGoal(50.0, 0.9, 1_000_000_000L));

        assertThat(verdict.reasonCode()).isEqualTo(ReasonCode.ALL_FAILED);
    }

    @Test
    void evaluates_the_surviving_runs_when_some_fleets_failed() {
        List<RunResult> partial = runs.stream()
                .filter(run -> List.of(2, 3, 8, 16).contains(run.amrCount()))
                .toList();

        EstimateVerdict verdict = evaluator.evaluate(partial, new EstimateGoal(50.0, 0.8, 1_000_000_000L));

        assertThat(verdict.recommendedCount()).isEqualTo(8);   // 4·6대가 없으니 8대가 최소
    }

    @Test
    void skips_knee_detection_with_two_or_fewer_points() {
        List<RunResult> twoPoints = runs.subList(0, 2);

        EstimateVerdict verdict = evaluator.evaluate(twoPoints, new EstimateGoal(10.0, 0.5, 1_000_000_000L));

        assertThat(verdict.kneeCount()).isNull();
        assertThat(verdict.recommendedCount()).isEqualTo(2);
    }

    @Test
    void sorts_by_fleet_size_regardless_of_input_order() {
        List<RunResult> shuffled = new ArrayList<>(runs);
        Collections.reverse(shuffled);

        EstimateVerdict verdict = evaluator.evaluate(shuffled, new EstimateGoal(50.0, 0.9, 1_000_000_000L));

        assertThat(verdict.recommendedCount()).isEqualTo(6);
        assertThat(verdict.kneeCount()).isEqualTo(8);
    }

    // ── 픽스처 ────────────────────────────────────────────────────────────────

    /** b0z 스윕에서 헤딩 모델·시드 42 행만 골라 RunResult 로 만든다. */
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
                loaded.add(new RunResult(
                        amrCount,
                        Double.parseDouble(f[col.get("orders_per_h")]),
                        Double.parseDouble(f[col.get("util_incl_service")]),
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
