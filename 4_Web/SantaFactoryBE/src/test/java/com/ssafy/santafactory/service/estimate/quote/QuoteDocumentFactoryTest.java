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
        assertThat(q.issue().statusLine()).isEqualTo("완료 · 28회 시뮬레이션 · 물리 검증 완료");
        assertThat(q.issue().elapsed()).isEqualTo("18분 42초");
        assertThat(q.issue().sizeLine()).isEqualTo("60 m × 40 m · 2,400 m²");
        assertThat(q.issue().windowLine()).isEqualTo("13:00 – 18:00 (5시간)");
        assertThat(q.issue().dailyOrders()).isEqualTo("1,000건");

        assertThat(q.verdict().recommended()).isTrue();
        assertThat(q.verdict().count()).isEqualTo(14);
        assertThat(q.verdict().lead()).contains("15대부터는 로봇을 늘려도").contains("2억 1,700만 원");
        assertThat(q.verdict().throughput()).isEqualTo("95.6");
        assertThat(q.verdict().throughputNote()).isEqualTo("목표 95 % 대비 +0.6p");
        assertThat(q.verdict().costEok()).isEqualTo("2.17");
        assertThat(q.verdict().costNote()).contains("72 %").contains("8,300만 원");
        assertThat(q.verdict().leadTimeMin()).isEqualTo("6.4");
        assertThat(q.verdict().leadTimeNote()).contains("평균은 3.5분");

        assertThat(q.targets()).extracting(QuoteDocument.TargetRow::label)
                .containsExactly("주문 처리율", "로봇 가동률", "구축 비용", "주문 처리 시간 (90 % 기준)");
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
        assertThat(v.methodLine()).startsWith("로봇 14대를 3D 물리 시뮬레이션");
        assertThat(v.windowLine()).isEqualTo("주문이 가장 몰리는 10분");
        assertThat(v.resultOk()).isTrue();
        assertThat(v.resultLine()).isEqualTo("정상 완료 · 로봇 14대 모두 가동");
        assertThat(v.hasComparison()).isTrue();
        assertThat(v.rows()).extracting(QuoteDocument.CompareRow::diff).containsExactly("−5 %", "+8 %", "+1.3 %p");
        assertThat(v.rows().get(1).warn()).isTrue();
        assertThat(v.rows().get(0).warn()).isFalse();
        assertThat(v.noticeText()).contains("약 8 % 길어질 수 있습니다").endsWith("권장 대수 판정에는 영향이 없습니다.");
    }

    @Test
    void unfinished_verification_hides_the_comparison() {
        QuoteDocument q = factory.build(new QuoteSource(
                QuoteFixtures.detail(142L, 14, 15, QuoteFixtures.verification(VerifyNoticeCode.NOT_FINISHED, null)),
                QuoteFixtures.warehouse()));

        assertThat(q.verification().hasComparison()).isFalse();
        assertThat(q.verification().resultOk()).isFalse();
        assertThat(q.verification().noticeText()).startsWith("물리 검증이 정상 종료되지 않아");
        assertThat(q.issue().statusLine()).doesNotContain("물리 검증 완료");
    }

    @Test
    void fleet_table_keeps_twelve_rows_including_recommended_knee_ends_and_budget_edge() {
        QuoteDocument q = factory.build(new QuoteSource(QuoteFixtures.detail(142L, 14, 15, null), QuoteFixtures.warehouse()));

        List<Integer> counts = q.fleet().stream().map(QuoteDocument.FleetRow::count).toList();
        assertThat(counts).hasSize(12).contains(1, 14, 15, 19, 20, 28).isSorted();
        QuoteDocument.FleetRow rec = q.fleet().stream().filter(QuoteDocument.FleetRow::recommended).findFirst().orElseThrow();
        assertThat(rec.count()).isEqualTo(14);
        assertThat(rec.cost()).isEqualTo("2억 1,700만 원");
        assertThat(rec.efficiency()).isEqualTo("67.1");
        assertThat(q.fleet().stream().filter(QuoteDocument.FleetRow::knee).map(QuoteDocument.FleetRow::count)).containsExactly(15);
        assertThat(q.fleet().stream().filter(f -> f.count() == 20).findFirst().orElseThrow().overBudget()).isTrue();
        assertThat(q.fleetNote()).contains("12대 · 13대는 처리율 미달로 제외").contains("웹 리포트에서");
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
        assertThat(c.recLabel()).isEqualTo("권장 14대 · 효율 67.1");
        assertThat(c.kneeLabel()).isEqualTo("15대부터 효과 정체");
        assertThat(c.budgetLabel()).isEqualTo("예산 3억 원");
        assertThat(c.xLabels()).extracting(QuoteDocument.AxisLabel::text).contains("1대", "14대", "28대");
        assertThat(c.yRight()).extracting(QuoteDocument.AxisLabel::text).containsExactly("0억", "1.5억", "3억", "4.5억", "6억");   // 28대 4.34억이 예산 3억보다 커서 축은 6억까지
        assertThat(QuoteDocumentFactory.niceCostMax(434_000_000L)).isEqualTo(600_000_000L);
    }

    @Test
    void ops_block_uses_the_recommended_run_detail() {
        QuoteDocument q = factory.build(new QuoteSource(QuoteFixtures.detail(142L, 14, 15, null), QuoteFixtures.warehouse()));

        assertThat(q.ops().leadMeanMin()).isEqualTo("3.5분");
        assertThat(q.ops().queueSec()).isEqualTo("48초");
        assertThat(q.ops().conflictPct()).isEqualTo("6.8");
        assertThat(q.ops().distanceKm()).isEqualTo("171");
    }

    @Test
    void keeps_the_recommendation_label_inside_the_chart() {
        // 효율이 100 에 가까우면 표식이 그림 꼭대기에 붙는다. 글자를 그대로 점 위에 두면 잘렸다.
        double topRecY = QuoteDocumentFactory.PAD_T + 2;

        assertThat(QuoteDocumentFactory.recLabelY(topRecY)).isGreaterThan(topRecY);
        assertThat(QuoteDocumentFactory.recLabelY(100)).isEqualTo(86);   // 여유가 있으면 지금처럼 점 위
    }

    @Test
    void flips_the_recommendation_label_when_it_would_run_off_the_left_edge() {
        // 권장이 가장 적은 대수면 표식이 왼쪽 끝이라, 왼쪽으로 쓴 글자가 그림 밖으로 나간다
        assertThat(QuoteDocumentFactory.recLabelAnchor(QuoteDocumentFactory.PAD_L)).isEqualTo("start");
        assertThat(QuoteDocumentFactory.recLabelX(QuoteDocumentFactory.PAD_L)).isGreaterThan(QuoteDocumentFactory.PAD_L);
        assertThat(QuoteDocumentFactory.recLabelAnchor(400)).isEqualTo("end");
    }

    @Test
    void no_recommendation_gives_a_reason_and_no_cost_or_targets() {
        EstimateDetailResponse d = new EstimateDetailResponse(7L, EstimateStatus.DONE, "iw.hub", 95.0, 60.0, 50_000_000L,
                null, null, null, ReasonCode.BUDGET_EXCEEDED, LocalDateTime.of(2026, 9, 17, 10, 0), LocalDateTime.of(2026, 9, 17, 10, 5),
                300L, null, null, QuoteFixtures.runs(7L, 5), null);

        QuoteDocument q = factory.build(new QuoteSource(d, QuoteFixtures.warehouse()));

        assertThat(q.verdict().recommended()).isFalse();
        assertThat(q.verdict().reasonText()).startsWith("예산 안에 드는 로봇 대수가 없습니다");
        assertThat(q.targets()).isEmpty();
        assertThat(q.cost()).isNull();
        assertThat(q.verification()).isNull();
        assertThat(q.ops()).isNull();
        assertThat(q.fleet()).hasSize(5);
        assertThat(q.curve().recX()).isEqualTo(-1);
    }
}
