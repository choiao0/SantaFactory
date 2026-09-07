package com.ssafy.santafactory.service.estimate;

import org.springframework.stereotype.Component;

import java.util.Comparator;
import java.util.List;
import java.util.Optional;

/**
 * 대수별 결과에서 권장 대수와 효율 감소 지점을 뽑는다.
 *
 * <p>실패한 run 은 애초에 리스트에 들어오지 않으므로 대수가 중간중간 비어 있을 수 있고,
 * 전 대수 실패면 빈 리스트가 들어온다. 둘 다 정상 입력으로 다룬다.
 */
@Component
public class EstimateEvaluator {

    /** 무릎 판정 — 대수당 처리량 증가분이 첫 구간 증가분의 이 비율 밑으로 떨어지는 첫 지점. */
    private static final double KNEE_RATIO = 0.2;

    public EstimateVerdict evaluate(List<RunResult> runs, EstimateGoal goal) {
        if (runs == null || runs.isEmpty()) {
            return EstimateVerdict.none(ReasonCode.ALL_FAILED, null);
        }

        List<RunResult> sorted = runs.stream()
                .sorted(Comparator.comparingInt(RunResult::amrCount))
                .toList();
        Integer knee = findKnee(sorted);

        Optional<RunResult> recommended = sorted.stream()
                .filter(run -> satisfies(run, goal))
                .findFirst();

        return recommended
                .map(run -> EstimateVerdict.of(run.amrCount(), knee))
                .orElseGet(() -> EstimateVerdict.none(reasonFor(sorted, goal), knee));
    }

    /** 처리량 ≥ 목표 · 가동률 ≥ 목표 · 비용 ≤ 예산. */
    private boolean satisfies(RunResult run, EstimateGoal goal) {
        return run.ordersPerH() >= goal.targetOrdersPerH()
                && run.utilization() >= goal.targetUtilization()
                && run.cost() <= goal.budget();
    }

    /** 어느 조건에서 처음 막혔는지 — 예산 → 처리량 → 가동률 순으로 좁힌다. */
    private ReasonCode reasonFor(List<RunResult> sorted, EstimateGoal goal) {
        List<RunResult> withinBudget = sorted.stream()
                .filter(run -> run.cost() <= goal.budget())
                .toList();
        if (withinBudget.isEmpty()) {
            return ReasonCode.BUDGET_EXCEEDED;
        }
        boolean throughputMet = withinBudget.stream()
                .anyMatch(run -> run.ordersPerH() >= goal.targetOrdersPerH());
        return throughputMet ? ReasonCode.UTILIZATION_SHORT : ReasonCode.THROUGHPUT_SHORT;
    }

    /**
     * 대수당 처리량 증가분이 처음 꺾이는 대수.
     * 점이 3개 미만이거나 첫 구간이 이미 안 오르면 판정하지 않는다(null).
     */
    private Integer findKnee(List<RunResult> sorted) {
        if (sorted.size() < 3) {
            return null;
        }
        double baseGain = gain(sorted.get(0), sorted.get(1));
        if (baseGain <= 0) {
            return null;
        }
        for (int i = 1; i < sorted.size() - 1; i++) {
            if (gain(sorted.get(i), sorted.get(i + 1)) < baseGain * KNEE_RATIO) {
                return sorted.get(i).amrCount();
            }
        }
        return null;
    }

    /** 대수 1대당 처리량 증가분. 대수가 같으면(중복 run) 0으로 본다. */
    private double gain(RunResult from, RunResult to) {
        int step = to.amrCount() - from.amrCount();
        return step <= 0 ? 0 : (to.ordersPerH() - from.ordersPerH()) / step;
    }
}
