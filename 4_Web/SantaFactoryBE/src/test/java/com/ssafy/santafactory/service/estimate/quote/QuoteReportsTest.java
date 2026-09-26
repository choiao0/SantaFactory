package com.ssafy.santafactory.service.estimate.quote;

import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse.Run;
import org.assertj.core.data.Offset;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.stream.IntStream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 견적서 3~5쪽 「도입 검토 보고서」 (S15P21A106-280). 픽스처: 1~28대, 권장 14대, 증설 효과 둔화 15대,
 * 13·14·15대 3D 주행 검증(14대 적합, 15대가 14대보다 수행률이 낮다).
 */
class QuoteReportsTest {

    private final QuoteDocumentFactory factory = new QuoteDocumentFactory(QuoteFixtures.PROPS, QuoteFixtures.PDF);

    private QuoteDocument withPhysics() {
        return factory.build(new QuoteSource(QuoteFixtures.detailWithPhysics(142L), QuoteFixtures.warehouse()));
    }

    @Test
    void a_recommended_estimate_gets_three_report_pages() {
        QuoteDocument q = withPhysics();

        assertThat(q.pages()).isEqualTo(5);
        assertThat(q.report()).isNotNull();
    }

    @Test
    void no_recommendation_means_no_report() {
        QuoteDocument q = factory.build(new QuoteSource(QuoteFixtures.detail(142L, null, null, null), QuoteFixtures.warehouse()));

        assertThat(q.pages()).isEqualTo(2);
        assertThat(q.report()).isNull();
    }

    @Test
    void basis_explains_the_rule_the_knee_the_waiting_and_the_3d_check() {
        QuoteReport r = withPhysics().report();

        assertThat(r.basis()).hasSize(4);
        assertThat(r.basis().get(0))
                .contains("운영 효율이 가장 높은 14대를 권장합니다")
                .contains("한 대 적은 13대는 주문 처리율이 93.2%로 목표 95%에 못 미칩니다");
        assertThat(r.basis().get(1)).contains("15대부터는").contains("13→14대는 시간당 4건이 늘어나지만 14→15대는 3.8건만 늘어납니다");
        assertThat(r.basis().get(2)).contains("평균 주문 처리 시간 3.5분").contains("로봇 배정 대기는 0.8분(23%)");
        assertThat(r.basis().get(3)).contains("권장 14대는 3D 주행 검증에서 적합 판정을 받았습니다").contains("80.5%")
                .doesNotContain("14대까지");   // 통과 상한이 권장과 같으면 되풀이하지 않는다
    }

    @Test
    void one_more_robot_is_weighed_against_its_3d_result() {
        QuoteReport r = withPhysics().report();

        assertThat(r.alternativeTitle()).isEqualTo("한 대 더 두는 경우 (15대)");
        assertThat(r.alternative())
                .contains("구축 비용이 1,550만 원 늘어나고")
                .contains("주문 처리율은 95.6%에서 97.9%로")
                .contains("로봇 가동률은 70.2%에서 66.9%로")
                .contains("15대가 주의 판정")
                .contains("80.5%에서 69.5%로");
    }

    @Test
    void method_names_the_sweep_the_rule_and_the_peak_window() {
        QuoteReport r = withPhysics().report();

        assertThat(r.method()).hasSize(3);
        assertThat(r.method().get(0)).contains("1~28대").contains("주문 1,000건").contains("6시간");
        assertThat(r.method().get(2)).contains("피크 작업 10분");
    }

    @Test
    void service_table_keeps_the_marked_counts_within_one_page() {
        QuoteReport r = withPhysics().report();

        assertThat(r.service()).hasSize(QuoteReports.SERVICE_ROWS);
        QuoteReport.ServiceRow rec = r.service().stream().filter(QuoteReport.ServiceRow::recommended).findFirst().orElseThrow();
        assertThat(rec.count()).isEqualTo(14);
        assertThat(rec.throughput()).isEqualTo("95.6%");
        assertThat(rec.perHour()).isEqualTo("159건");
        assertThat(rec.leadMean()).isEqualTo("3.5분");
        assertThat(rec.leadP90()).isEqualTo("6.4분");
        assertThat(rec.queueShare()).isEqualTo("23%");
        assertThat(rec.conflict()).isEqualTo("6.8%");
        assertThat(rec.cost()).isEqualTo("2억 1,700만 원");
        assertThat(r.service()).extracting(QuoteReport.ServiceRow::count).contains(1, 14, 15, 19, 20, 28);
    }

    @Test
    void wait_chart_stacks_waiting_under_work_for_every_row() {
        QuoteReport.WaitChart c = withPhysics().report().waitChart();

        assertThat(c.bars()).hasSize(QuoteReports.SERVICE_ROWS);
        QuoteReport.WaitBar rec = c.bars().stream().filter(QuoteReport.WaitBar::recommended).findFirst().orElseThrow();
        // 대기 0.8분 : 이동·작업 2.7분 — 막대 높이도 같은 비율
        assertThat(rec.hQueue() / rec.hWork()).isCloseTo(48.0 / 164.0, Offset.offset(0.01));
        assertThat(rec.yWork() + rec.hWork() + QuoteReports.GAP).isCloseTo(rec.yQueue(), Offset.offset(0.01));
        assertThat(rec.p90Y()).isLessThan(rec.yWork());
        assertThat(c.yTicks()).first().extracting(QuoteDocument.AxisLabel::text).isEqualTo("0");
    }

    @Test
    void marginal_gain_is_charted_and_priced_around_the_recommendation() {
        QuoteReport r = withPhysics().report();

        assertThat(r.marginal().bars()).hasSize(27);
        assertThat(r.marginal().bars().stream().filter(QuoteReport.GainBar::recommended).map(QuoteReport.GainBar::count))
                .containsExactly(14);
        assertThat(r.marginalRows()).extracting(QuoteReport.MarginalRow::count).containsExactly(13, 14, 15, 16);
        QuoteReport.MarginalRow rec = r.marginalRows().get(1);
        assertThat(rec.gain()).isEqualTo("+4건");
        assertThat(rec.costPerGain()).isEqualTo("388만 원");
        assertThat(r.marginalRows().get(3).costPerGain()).isEqualTo("2,325만 원");
        assertThat(r.marginalNote()).contains("14번째 로봇은 시간당 처리 주문 1건을 늘리는 데 388만 원이 들고, 15번째 로봇은 404만 원이 듭니다");
    }

    @Test
    void peak_rows_show_each_count_s_own_window_on_the_clock() {
        QuoteReport r = withPhysics().report();

        assertThat(r.peak()).extracting(QuoteReport.PeakRow::window)
                .containsExactly("18:19–18:29", "15:47–15:57", "15:57–16:07");
        QuoteReport.PeakRow rec = r.peak().get(1);
        assertThat(rec.recommended()).isTrue();
        assertThat(rec.verdict()).isEqualTo("적합");
        assertThat(rec.ratio()).isEqualTo("80.5%");
        assertThat(rec.lagP50()).isEqualTo("62초");
        assertThat(rec.lagP90()).isEqualTo("126초");
        assertThat(rec.contacts()).isEqualTo("0회");
        assertThat(rec.minGap()).isEqualTo("0.03 m");
        assertThat(r.peakNote()).contains("구간이 대수마다 다릅니다").contains("80% 이상");
    }

    @Test
    void risks_follow_the_numbers_and_assumptions_state_the_limits() {
        QuoteReport r = withPhysics().report();

        assertThat(r.risks()).anySatisfy(s -> assertThat(s).contains("계획한 이동과 작업의 80.5%"));
        assertThat(r.risks()).anySatisfy(s -> assertThat(s).contains("15대의 계획 대비 수행률이 14대보다 낮습니다"));
        assertThat(r.risks()).noneSatisfy(s -> assertThat(s).contains("여유가 거의 없습니다"));   // 가동률 70.2%
        assertThat(r.assumptions()).anySatisfy(s -> assertThat(s).contains("13:00–18:00").contains("1,000건").contains("6시간"));
        assertThat(r.assumptions()).anySatisfy(s -> assertThat(s).contains("배터리 충전"));
    }

    @Test
    void report_text_keeps_internal_terms_out() {
        QuoteReport r = withPhysics().report();
        // 단계 설명은 "제목 — 본문" 으로 넘기고 템플릿이 나눈다 — 본문만 본다
        String steps = String.join(" ", r.method().stream().map(m -> m.substring(m.indexOf(" — ") + 3)).toList());
        String all = String.join(" ", r.basis()) + r.alternative() + steps + r.serviceNote() + r.waitNote()
                + r.marginalNote() + r.peakNote() + String.join(" ", r.risks()) + String.join(" ", r.assumptions());

        for (String banned : new String[]{"DES", "Isaac", "무릎", "리드타임", "물리 검증", "주문 집중", "창 동작", "스윕", "θ",
                " — ", "동작", "상위 10% 주문 처리"}) {
            assertThat(all).doesNotContain(banned);
        }
    }

    // ── 빈 분기 · 경계 (리뷰 반영) ──────────────────────────────────────────

    /** 픽스처를 고쳐 쓴다 — 목표 · 권장 · 둔화 지점 · 대수별 결과 · 3D 검증만 바꾼다. */
    private static EstimateDetailResponse with(EstimateDetailResponse d, double thr, double utl, Integer rec, Integer knee,
                                               List<Run> runs, List<EstimateDetailResponse.VerificationRun> checks, Integer limit) {
        return new EstimateDetailResponse(d.estimateId(), d.status(), d.amrModel(), thr, utl, d.budgetLimit(), rec, rec, knee,
                d.reasonCode(), d.createdAt(), d.completedAt(), d.elapsedSeconds(), null, null, runs, d.verification(), checks, limit);
    }

    private QuoteReport report(EstimateDetailResponse d) {
        return factory.build(new QuoteSource(d, QuoteFixtures.warehouse())).report();
    }

    @Test
    void the_largest_count_has_no_one_more_case() {
        var d = QuoteFixtures.detailWithPhysics(142L);
        QuoteReport r = report(with(d, 95.0, 60.0, 28, null, d.runs(), List.of(), null));

        assertThat(r.alternativeTitle()).isNull();
        assertThat(r.alternative()).isNull();
        assertThat(r.marginalRows()).extracting(QuoteReport.MarginalRow::count).containsExactly(27, 28);
        assertThat(r.marginalNote()).isEqualTo("28번째 로봇을 더해도 처리량은 거의 늘지 않습니다.");   // 금액을 안 적었으면 비용 기준도 안 적는다
    }

    @Test
    void no_3d_check_leaves_the_basis_and_peak_table_out() {
        QuoteReport r = report(QuoteFixtures.detail(142L, 14, 15, null));

        assertThat(r.basis()).hasSize(3).noneSatisfy(b -> assertThat(b).contains("3D"));
        assertThat(r.peak()).isEmpty();
        assertThat(r.risks()).containsExactly("특별히 확인된 운영 위험은 없습니다.");
    }

    @Test
    void runs_without_detail_metrics_drop_the_two_charts() {
        var d = QuoteFixtures.detail(142L, 14, 15, null);
        List<Run> bare = d.runs().stream().map(x -> new Run(x.runId(), x.amrCount(), x.status(), x.throughput(), x.utilization(),
                x.outbound(), x.totalCost(), x.leadTimeP90(), null, null)).toList();
        QuoteReport r = report(with(d, 95.0, 60.0, 14, 15, bare, List.of(), null));

        assertThat(r.waitChart()).isNull();
        assertThat(r.marginal()).isNull();
        assertThat(r.basis()).hasSize(2);                          // 규칙 · 둔화 지점(증가량 없이)
        assertThat(r.basis().get(1)).isEqualTo("15대부터는 로봇을 늘려도 주문 처리량이 거의 늘지 않습니다(증설 효과 둔화 지점).");
        assertThat(r.service()).allSatisfy(x -> assertThat(x.perHour()).isEqualTo("—"));
    }

    @Test
    void peak_table_keeps_the_counts_nearest_the_recommendation() {
        var d = QuoteFixtures.detailWithPhysics(142L);
        List<EstimateDetailResponse.VerificationRun> many = IntStream.rangeClosed(1, 15)
                .mapToObj(n -> QuoteFixtures.physicsRun(n, "WARN", 0.7, 60.0, 120.0, 0, 0.3, 10_000.0)).toList();
        QuoteReport r = report(with(d, 95.0, 60.0, 14, 15, d.runs(), many, null));

        assertThat(r.peak()).extracting(QuoteReport.PeakRow::count).containsExactly(10, 11, 12, 13, 14, 15);   // 가까운 6개를 대수 순으로
        assertThat(r.peakNote()).contains("나머지는 견적 결과 화면에서");
    }

    @Test
    void a_tiny_drop_is_not_written_as_minus_zero() {
        var d = QuoteFixtures.detail(142L, 14, 15, null);
        List<Run> runs = d.runs().stream().map(x -> x.amrCount() != 15 ? x : new Run(x.runId(), 15, x.status(), x.throughput(),
                x.utilization(), x.outbound(), x.totalCost(), x.leadTimeP90(), null,
                new EstimateDetailResponse.RunKpi(1000, 956, 212.0, 48.0, 956 / 6.0 - 0.03, 0.068, 171_400L))).toList();
        QuoteReport r = report(with(d, 95.0, 60.0, 14, 15, runs, List.of(), null));

        assertThat(r.marginalRows()).filteredOn(m -> m.count() == 15).extracting(QuoteReport.MarginalRow::gain).containsExactly("0건");
        assertThat(r.basis().get(1)).contains("14→15대는 처리량이 늘지 않습니다");
    }

    @Test
    void the_smaller_count_is_excluded_for_the_target_it_actually_misses() {
        var d = QuoteFixtures.detail(142L, 14, 15, null);
        // 처리율 목표 90%는 13대(93.2%)도 넘지만 가동률 목표 75%는 못 넘는다(73.1%)
        QuoteReport r = report(with(d, 90.0, 75.0, 14, 15, d.runs(), List.of(), null));

        assertThat(r.basis().get(0)).contains("한 대 적은 13대는 로봇 가동률이 73.1%로 목표 75%에 못 미칩니다")
                .doesNotContain("목표는 충족하지만");
    }
}
