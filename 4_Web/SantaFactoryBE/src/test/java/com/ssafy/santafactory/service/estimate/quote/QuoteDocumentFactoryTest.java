package com.ssafy.santafactory.service.estimate.quote;

import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.dto.estimate.VerifyNoticeCode;
import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.entity.estimate.ReasonCode;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;
import java.util.List;
import java.util.stream.IntStream;

import static org.assertj.core.api.Assertions.assertThat;

class QuoteDocumentFactoryTest {

    private final QuoteDocumentFactory factory = new QuoteDocumentFactory(QuoteFixtures.PROPS, QuoteFixtures.PDF);

    @Test
    void builds_the_summary_page_from_the_recommended_run() {
        QuoteDocument q = factory.build(new QuoteSource(
                QuoteFixtures.detail(142L, 14, 15, QuoteFixtures.verification(VerifyNoticeCode.SLOWER_AT_PEAK, QuoteFixtures.slowerAtPeak())),
                QuoteFixtures.warehouse()));

        assertThat(q.docNo()).isEqualTo("EST-20260917-0142");
        assertThat(q.fileName()).isEqualTo("견적서_EST-20260917-0142.pdf");
        assertThat(q.issue().statusLine()).isEqualTo("완료 · 대수별 시뮬레이션 28회 · 3D 주행 검증 완료");
        assertThat(q.issue().sizeLine()).isEqualTo("60 m × 40 m · 2,400 m²");
        assertThat(q.issue().windowLine()).isEqualTo("13:00 – 18:00 (5시간)");
        assertThat(q.issue().dailyOrders()).isEqualTo("1,000건");

        assertThat(q.verdict().recommended()).isTrue();
        assertThat(q.verdict().count()).isEqualTo(14);
        assertThat(q.verdict().lead()).contains("15대부터는 로봇을 늘려도").contains("2억 1,700만 원");
        assertThat(q.verdict().throughput()).isEqualTo("95.6");
        assertThat(q.verdict().throughputNote()).isEqualTo("목표 95% 대비 +0.6%p");
        assertThat(q.verdict().costEok()).isEqualTo("2.17");
        assertThat(q.verdict().costNote()).contains("72%").contains("8,300만 원");
        assertThat(q.verdict().leadTimeMin()).isEqualTo("6.4");
        assertThat(q.verdict().leadTimeNote()).contains("평균 3.5분");

        assertThat(q.targets()).extracting(QuoteDocument.TargetRow::label)
                .containsExactly("주문 처리율", "로봇 가동률", "구축 비용", "주문 처리 시간 (90% 기준)");
        assertThat(q.targets().get(0).ok()).isTrue();
        assertThat(q.targets().get(0).note()).isEqualTo("하루 1,000건 중 956건 처리");
        assertThat(q.targets().get(3).ok()).isNull();
        assertThat(q.targets().get(3).target()).isEqualTo("판정에 미포함");

        assertThat(q.cost().unitAmount()).isEqualTo("210,000,000");
        assertThat(q.cost().installAmount()).isEqualTo("7,000,000");
        assertThat(q.cost().extraLabel()).isNull();
        assertThat(q.cost().total()).isEqualTo("217,000,000");
        assertThat(q.cost().usedPctText()).isEqualTo("72.3");
        assertThat(q.cost().remaining()).isEqualTo("83,000,000");
    }

    @Test
    void verification_block_compares_and_explains_the_notice() {
        QuoteDocument q = factory.build(new QuoteSource(
                QuoteFixtures.detail(142L, 14, 15, QuoteFixtures.verification(VerifyNoticeCode.SLOWER_AT_PEAK, QuoteFixtures.slowerAtPeak())),
                QuoteFixtures.warehouse()));

        QuoteDocument.Verification v = q.verification();
        assertThat(v.methodLine()).startsWith("로봇 14대를 실제 크기와 속도로");
        assertThat(v.windowLine()).isEqualTo("주문 집중 10분");
        assertThat(v.resultOk()).isTrue();
        assertThat(v.resultLine()).isEqualTo("완료 · 로봇 14대 모두 가동");
        assertThat(v.hasComparison()).isTrue();
        assertThat(v.rows()).extracting(QuoteDocument.CompareRow::diff).containsExactly("−5%", "+8%", "+1.3%p");
        assertThat(v.rows().get(1).warn()).isTrue();
        assertThat(v.rows().get(0).warn()).isFalse();
        // 느려질 수 있다는 안내에는 산정 근거 문장을 붙이지 않는다
        assertThat(v.noticeText()).endsWith("약 8% 길어질 수 있습니다.").doesNotContain("권장 대수");
    }

    @Test
    void unfinished_verification_hides_the_comparison_and_the_raw_error() {
        var failed = new EstimateDetailResponse.Verification("failed", VerifyNoticeCode.NOT_FINISHED, 14, 0, 600,
                "runner exited with code 137", LocalDateTime.of(2026, 9, 17, 15, 0), null);
        QuoteDocument q = factory.build(new QuoteSource(QuoteFixtures.detail(142L, 14, 15, failed), QuoteFixtures.warehouse()));

        assertThat(q.verification().hasComparison()).isFalse();
        assertThat(q.verification().resultOk()).isFalse();
        // 내부 오류 문구는 DB·로그에만 남고 견적서에는 고정 문장만 나간다
        assertThat(q.verification().resultLine()).isEqualTo("검증을 완료하지 못했습니다.");
        assertThat(q.verification().noticeText()).startsWith("3D 주행 검증을 완료하지 못해")
                .endsWith("권장 대수는 대수별 시뮬레이션 결과로 산정했습니다.").doesNotContain("137");
        assertThat(q.issue().statusLine()).doesNotContain("3D 주행 검증 완료");
    }

    @Test
    void physics_rows_use_customer_verdict_labels_and_state_the_pass_limit() {
        var d = QuoteFixtures.detail(142L, 14, 15, null);
        List<EstimateDetailResponse.VerificationRun> runs = List.of(
                physicsRun(13, "PASS"), physicsRun(14, "WARN"), physicsRun(15, "FAIL"), physicsRun(16, "NA"));

        QuoteDocument passed = factory.build(new QuoteSource(withPhysics(d, runs, 13), QuoteFixtures.warehouse()));
        QuoteDocument none = factory.build(new QuoteSource(withPhysics(d, runs, null), QuoteFixtures.warehouse()));
        QuoteDocument notRun = factory.build(new QuoteSource(d, QuoteFixtures.warehouse()));

        assertThat(passed.physicsRows()).extracting(QuoteDocument.PhysicsRow::verdictLabel)
                .containsExactly("적합", "주의", "부적합", "판정 불가");
        assertThat(passed.physicsLimitLine()).isEqualTo("13대까지 3D 주행 검증을 통과했습니다.");
        assertThat(none.physicsLimitLine()).isEqualTo("아직 3D 주행 검증을 통과한 대수가 없습니다.");
        assertThat(notRun.physicsLimitLine()).isNull();
    }

    private static EstimateDetailResponse.VerificationRun physicsRun(int n, String verdict) {
        return new EstimateDetailResponse.VerificationRun(n, 1, "DONE", verdict, null, null, null, null, null, null,
                LocalDateTime.of(2026, 9, 17, 15, 0), LocalDateTime.of(2026, 9, 17, 15, 20));
    }

    private static EstimateDetailResponse withPhysics(EstimateDetailResponse d, List<EstimateDetailResponse.VerificationRun> runs,
                                                      Integer limit) {
        return new EstimateDetailResponse(d.estimateId(), d.status(), d.amrModel(), d.targetThroughput(), d.targetUtilization(),
                d.budgetLimit(), d.recommendedCount(), d.minimalCount(), d.kneeCount(), d.reasonCode(), d.createdAt(),
                d.completedAt(), d.elapsedSeconds(), null, null, d.runs(), d.verification(), runs, limit);
    }

    @Test
    void fleet_table_keeps_ten_rows_including_recommended_knee_ends_and_budget_edge() {
        QuoteDocument q = factory.build(new QuoteSource(QuoteFixtures.detail(142L, 14, 15, null), QuoteFixtures.warehouse()));

        List<Integer> counts = q.fleet().stream().map(QuoteDocument.FleetRow::count).toList();
        assertThat(counts).hasSize(10).contains(1, 14, 15, 19, 20, 28).isSorted();
        QuoteDocument.FleetRow rec = q.fleet().stream().filter(QuoteDocument.FleetRow::recommended).findFirst().orElseThrow();
        assertThat(rec.count()).isEqualTo(14);
        assertThat(rec.cost()).isEqualTo("2억 1,700만 원");
        assertThat(rec.efficiency()).isEqualTo("67.1%");
        assertThat(q.fleet().stream().filter(QuoteDocument.FleetRow::knee).map(QuoteDocument.FleetRow::count)).containsExactly(15);
        assertThat(q.fleet().stream().filter(f -> f.count() == 20).findFirst().orElseThrow().overBudget()).isTrue();
        assertThat(q.fleetNote()).contains("12대 · 13대는 운영 효율이 더 높지만 주문 처리율이 목표에 미달해 제외했습니다.").contains("견적 결과 화면에서");
    }

    @Test
    void small_sweeps_keep_every_run() {
        List<Integer> all = IntStream.rangeClosed(3, 9).boxed().toList();
        assertThat(QuoteDocumentFactory.pickRows(all, 6, 5, 7, null)).isEqualTo(all);
    }

    @Test
    void curve_has_both_lines_and_the_markers() {
        QuoteDocument q = factory.build(new QuoteSource(QuoteFixtures.detail(142L, 14, 15, null), QuoteFixtures.warehouse()));

        QuoteDocument.Curve c = q.curve();
        assertThat(c.effPath()).startsWith("M36.0 ").contains(" L");
        assertThat(c.costPath()).startsWith("M36.0 ");
        assertThat(c.recLabel()).isEqualTo("권장 14대 · 운영 효율 67.1%");
        assertThat(c.budgetLabel()).isEqualTo("예산 3억 원");
        assertThat(c.xLabels()).extracting(QuoteDocument.AxisLabel::text).contains("1대", "14대", "28대");
        assertThat(c.yRight()).extracting(QuoteDocument.AxisLabel::text).containsExactly("0억", "1.5억", "3억", "4.5억", "6억");   // 28대 4.34억이 예산 3억보다 커서 축은 6억까지
        assertThat(QuoteDocumentFactory.niceCostMax(434_000_000L)).isEqualTo(600_000_000L);
    }

    @Test
    void ops_block_uses_the_recommended_run_detail() {
        QuoteDocument q = factory.build(new QuoteSource(QuoteFixtures.detail(142L, 14, 15, null), QuoteFixtures.warehouse()));

        assertThat(q.ops().leadMeanMin()).isEqualTo("3.5분");
        assertThat(q.ops().queueMin()).isEqualTo("0.8분");
        assertThat(q.ops().conflictPct()).isEqualTo("6.8");
        assertThat(q.ops().distanceKm()).isEqualTo("171");
    }

    @Test
    void marks_the_minimal_and_peak_configurations_on_the_curves() {
        // 이름은 그림이 아니라 범례에 적는다 — 표식은 자리만 잡는다 (S15P21A106-271)
        var d = QuoteFixtures.detail(142L, 14, 15, null);
        var adjacent = new EstimateDetailResponse(d.estimateId(), d.status(), d.amrModel(),
                d.targetThroughput(), d.targetUtilization(), d.budgetLimit(), 14, 13, d.kneeCount(),
                null, d.createdAt(), d.completedAt(), d.elapsedSeconds(), null, null, d.runs(), null, List.of(), null);

        QuoteDocument.Curve c = factory.build(new QuoteSource(adjacent, QuoteFixtures.warehouse())).curve();

        assertThat(c.minimal().label()).isEqualTo("최소 구성 13대");
        // 같은 대수라도 두 그림에서 점 높이가 다르다
        assertThat(c.minimal().x()).isEqualTo(c.minimalThr().x());
        assertThat(c.minimal().y()).isNotEqualTo(c.minimalThr().y());
        // 어느 대수도 처리율 100 %에 닿지 않는 픽스처라 처리율 그림에는 권장이 찍힌다
        assertThat(c.thrPeak().label()).isEqualTo("권장 14대");
    }

    @Test
    void no_recommendation_gives_a_reason_and_no_cost_or_targets() {
        EstimateDetailResponse d = new EstimateDetailResponse(7L, EstimateStatus.DONE, "iw.hub", 95.0, 60.0, 50_000_000L,
                null, null, null, ReasonCode.BUDGET_EXCEEDED, LocalDateTime.of(2026, 9, 17, 10, 0), LocalDateTime.of(2026, 9, 17, 10, 5),
                300L, null, null, QuoteFixtures.runs(7L, 5), null, List.of(), null);

        QuoteDocument q = factory.build(new QuoteSource(d, QuoteFixtures.warehouse()));

        assertThat(q.verdict().recommended()).isFalse();
        assertThat(q.verdict().reasonText()).startsWith("예산 안에서 도입할 수 있는 로봇 대수가 없습니다");
        assertThat(q.targets()).isEmpty();
        assertThat(q.cost()).isNull();
        assertThat(q.verification()).isNull();
        assertThat(q.ops()).isNull();
        assertThat(q.fleet()).hasSize(5);
        assertThat(q.curve().recX()).isEqualTo(-1);
    }
}
