package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.entity.estimate.ReasonCode;

import org.springframework.stereotype.Component;

import java.util.Comparator;
import java.util.List;
import java.util.Optional;

/**
 * 대수별 결과에서 권장 대수와 효율 감소 지점을 뽑는다.
 *
 * <p>실패한 run 은 애초에 리스트에 들어오지 않으므로 대수가 중간중간 비어 있을 수 있고,
 * 전 대수 실패면 빈 리스트가 들어온다. 둘 다 정상 입력으로 다룬다.
 *
 * <p><b>대수를 늘리면 처리율이 계속 오른다고 보지 않는다</b> (S15P21A106-97). FMS 실측(v3.6,
 * 6,000건/6h)은 18대에서 97.2 % 로 포화한 뒤 24대 97.0 %, 28대 96.9 % 로 오히려 내려간다 —
 * 혼잡이 늘어서다. 판정은 "조건을 만족하는 최소 대수"라 이 하락에 영향받지 않지만, 무릎은
 * 증가분을 보는 값이라 기준을 어디서 잡느냐가 곧 답을 바꾼다.
 */
@Component
public class EstimateEvaluator {

    /** 무릎 판정 — 대수당 처리율 증가분이 가장 가파른 구간의 이 비율 밑으로 떨어지는 첫 지점. */
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

    /** 처리율 ≥ 목표 · 가동률 ≥ 목표 · 비용 ≤ 예산 · 리드타임 p90 ≤ 상한. */
    private boolean satisfies(RunResult run, EstimateGoal goal) {
        return run.throughputPercent() >= goal.targetThroughputPercent()
                && run.utilizationPercent() >= goal.targetUtilizationPercent()
                && run.cost() <= goal.budgetLimit()
                && withinLeadTime(run, goal);
    }

    /**
     * 주문 리드타임 p90 이 상한 안인가 (S15P21A106-97).
     *
     * <p>상한이 설정돼 있지 않거나 시뮬이 값을 주지 않았으면 <b>통과</b>로 본다 — 없는 값으로
     * 대수를 떨어뜨리면 "리드타임 때문에 권장이 없다"는 틀린 사유가 나온다.
     *
     * <p>이 조건은 대수가 늘수록 만족하기 쉬워진다(일을 나눠 지니 대기가 준다). 즉 처리율과 같은
     * 방향으로 작용해 권장 대수를 <b>올린다</b> — 상한을 좁게 잡으면 견적 금액이 함께 오른다.
     */
    private boolean withinLeadTime(RunResult run, EstimateGoal goal) {
        Double limit = goal.leadTimeP90LimitSeconds();
        Double actual = run.leadTimeP90Seconds();
        return limit == null || actual == null || actual <= limit;
    }

    /** 어느 조건에서 처음 막혔는지 — 예산 → 처리율 → 가동률 → 리드타임 순으로 좁힌다. */
    private ReasonCode reasonFor(List<RunResult> sorted, EstimateGoal goal) {
        List<RunResult> withinBudget = sorted.stream()
                .filter(run -> run.cost() <= goal.budgetLimit())
                .toList();
        if (withinBudget.isEmpty()) {
            return ReasonCode.BUDGET_EXCEEDED;
        }
        List<RunResult> throughputMet = withinBudget.stream()
                .filter(run -> run.throughputPercent() >= goal.targetThroughputPercent())
                .toList();
        if (throughputMet.isEmpty()) {
            return ReasonCode.THROUGHPUT_SHORT;
        }
        boolean utilizationMet = throughputMet.stream()
                .anyMatch(run -> run.utilizationPercent() >= goal.targetUtilizationPercent());
        // 앞의 셋을 다 통과한 대수가 있는데도 권장이 없다면 남은 조건은 리드타임뿐이다
        return utilizationMet ? ReasonCode.LEAD_TIME_LONG : ReasonCode.UTILIZATION_SHORT;
    }

    /**
     * 대수당 처리율 증가분이 처음 꺾이는 대수.
     *
     * <p>기준은 <b>가장 가파른 구간</b>의 증가분이다. 예전에는 첫 구간을 기준으로 삼았는데, 그건
     * 1대부터 도는 전량 스윕을 전제한 것이었다 — 화면에서 대수 범위를 좁게 고르면(02 FLEET) 그
     * 구간은 이미 포화 근처라 첫 구간 증가분이 0 이하가 되고, 그러면 무릎을 아예 포기해 그래프에
     * "효율 감소 시작 구간"이 영영 안 그려졌다 (S15P21A106-97). 전량 스윕에서는 보통 첫 구간이
     * 가장 가파르므로 종전과 같은 답이 나온다.
     *
     * <p>가장 가파른 구간보다 <b>뒤</b>에서만 찾는다. 앞에서 찾으면 오르기도 전에 무릎이 잡힌다.
     * 점이 3개 미만이거나 어디서도 오르지 않으면 판정하지 않는다(null).
     */
    private Integer findKnee(List<RunResult> sorted) {
        if (sorted.size() < 3) {
            return null;
        }
        int steepest = steepestIndex(sorted);
        double bestGain = gain(sorted.get(steepest), sorted.get(steepest + 1));
        if (bestGain <= 0) {
            return null;
        }
        for (int i = steepest + 1; i < sorted.size() - 1; i++) {
            if (gain(sorted.get(i), sorted.get(i + 1)) < bestGain * KNEE_RATIO) {
                return sorted.get(i).amrCount();
            }
        }
        return null;
    }

    /** 증가분이 가장 큰 구간의 시작 인덱스. 같은 값이면 앞쪽을 쓴다 — 무릎을 늦추지 않으려고. */
    private int steepestIndex(List<RunResult> sorted) {
        int best = 0;
        double bestGain = gain(sorted.get(0), sorted.get(1));
        for (int i = 1; i < sorted.size() - 1; i++) {
            double current = gain(sorted.get(i), sorted.get(i + 1));
            if (current > bestGain) {
                bestGain = current;
                best = i;
            }
        }
        return best;
    }

    /** 대수 1대당 처리율 증가분(%p). 대수가 같으면(중복 run) 0으로 본다. */
    private double gain(RunResult from, RunResult to) {
        int step = to.amrCount() - from.amrCount();
        return step <= 0 ? 0 : (to.throughputPercent() - from.throughputPercent()) / step;
    }
}
