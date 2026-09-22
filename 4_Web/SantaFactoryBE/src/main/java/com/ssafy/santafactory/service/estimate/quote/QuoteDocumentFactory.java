package com.ssafy.santafactory.service.estimate.quote;

import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse.Run;
import com.ssafy.santafactory.dto.estimate.VerifyNoticeCode;
import com.ssafy.santafactory.dto.warehouse.WarehouseResponse;
import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.entity.estimate.ReasonCode;
import com.ssafy.santafactory.entity.estimate.RunStatus;
import com.ssafy.santafactory.service.estimate.EstimateProperties;
import com.ssafy.santafactory.service.estimate.quote.QuoteDocument.AxisLabel;
import com.ssafy.santafactory.service.estimate.quote.QuoteDocument.CompareRow;
import com.ssafy.santafactory.service.estimate.quote.QuoteDocument.Cost;
import com.ssafy.santafactory.service.estimate.quote.QuoteDocument.Curve;
import com.ssafy.santafactory.service.estimate.quote.QuoteDocument.FleetRow;
import com.ssafy.santafactory.service.estimate.quote.QuoteDocument.Issue;
import com.ssafy.santafactory.service.estimate.quote.QuoteDocument.Ops;
import com.ssafy.santafactory.service.estimate.quote.QuoteDocument.TargetRow;
import com.ssafy.santafactory.service.estimate.quote.QuoteDocument.Verdict;
import com.ssafy.santafactory.service.estimate.quote.QuoteDocument.Verification;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Base64;
import java.util.Comparator;
import java.util.EnumMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TreeSet;

import static com.ssafy.santafactory.service.estimate.quote.QuoteFormat.comma;
import static com.ssafy.santafactory.service.estimate.quote.QuoteFormat.eok;
import static com.ssafy.santafactory.service.estimate.quote.QuoteFormat.minutes;
import static com.ssafy.santafactory.service.estimate.quote.QuoteFormat.oneDecimal;
import static com.ssafy.santafactory.service.estimate.quote.QuoteFormat.pct;
import static com.ssafy.santafactory.service.estimate.quote.QuoteFormat.ratioPct;
import static com.ssafy.santafactory.service.estimate.quote.QuoteFormat.won;

/**
 * 견적 상세 응답 + 창고 → 견적서 템플릿 값 (S15P21A106-236). 문구 원칙은 구성안 "문서 원칙" 표를 따른다:
 * 창고 관리자 용어, 충전기·입고 없음, 계산 조건 노출 없음.
 */
@Component
@RequiredArgsConstructor
@EnableConfigurationProperties(QuotePdfProperties.class)
public class QuoteDocumentFactory {

    /** 2면 비교표 행 수 — A4 한 면에 그래프·운영 예상·유의 사항까지 들어가는 최대치. */
    static final int FLEET_ROWS = 12;

    static final double SVG_W = 672, SVG_H = 175, PAD_L = 36, PAD_R = 48, PAD_T = 14, PAD_B = 22;

    private static final Map<ReasonCode, String> REASON_TEXT = new EnumMap<>(Map.of(
            ReasonCode.BUDGET_EXCEEDED, "예산 안에 드는 로봇 대수가 없습니다. 예산을 올리거나 목표를 낮춰 다시 요청해 주세요.",
            ReasonCode.THROUGHPUT_SHORT, "예산 안의 대수로는 목표 주문 처리율에 닿지 않습니다. 목표를 낮추거나 예산을 올려야 합니다.",
            ReasonCode.UTILIZATION_SHORT, "목표 처리율은 채우지만 그 대수의 로봇 가동률이 목표에 못 미칩니다. 가동률 목표를 조정해 보세요.",
            ReasonCode.LEAD_TIME_LONG, "주문은 목표만큼 처리되지만 한 건이 끝나기까지 걸리는 시간이 상한을 넘습니다. 대수를 늘리거나 상한을 완화해야 합니다.",
            ReasonCode.ALL_FAILED, "모든 대수의 시뮬레이션이 실패해 판정할 결과가 없습니다. 조건을 확인한 뒤 다시 요청해 주세요.",
            ReasonCode.LOAD_TOO_LOW, "모든 대수가 처리율 100 %를 기록해 대수를 구분할 수 없습니다. 주문량이 너무 적습니다."));

    private final EstimateProperties estimateProperties;
    private final QuotePdfProperties pdfProperties;
    private final String logoDataUri = loadLogo();

    public QuoteDocument build(QuoteSource source) {
        EstimateDetailResponse d = source.detail();
        WarehouseResponse w = source.warehouse();
        List<Run> done = d.runs().stream()
                .filter(r -> r.status() == RunStatus.DONE && r.throughput() != null)
                .sorted(Comparator.comparingInt(Run::amrCount))
                .toList();
        Run rec = d.recommendedCount() == null ? null
                : done.stream().filter(r -> d.recommendedCount().equals(r.amrCount())).findFirst().orElse(null);

        String docNo = QuoteFormat.docNo(d.createdAt(), d.estimateId());
        String model = modelName(d.amrModel());
        return new QuoteDocument(
                docNo,
                QuoteFormat.dateTime(d.createdAt()),
                "견적서_" + docNo + ".pdf",
                issue(d, w, model),
                verdict(d, rec, model),
                rec == null ? List.of() : targets(d, rec, w),
                rec == null ? null : cost(d, rec),
                rec == null ? null : verification(d, rec),
                fleet(d, done),
                fleetNote(d, rec, done),
                done.size() >= 2 ? curve(d, done) : null,
                rec == null || rec.kpi() == null ? null : ops(rec),
                pdfProperties.siteUrl() + "/estimates",
                logoDataUri);
    }

    // ── 01 ─────────────────────────────────────────────────────────────────

    private Issue issue(EstimateDetailResponse d, WarehouseResponse w, String model) {
        StringBuilder status = new StringBuilder(d.status() == EstimateStatus.PARTIAL ? "일부 실패" : "완료");
        status.append(" · ").append(d.runs().size()).append("회 시뮬레이션");
        if (d.verification() != null && d.verification().notice() != VerifyNoticeCode.NOT_FINISHED) {
            status.append(" · 물리 검증 완료");
        }
        String window = "—";
        if (w.outboundStart() != null && w.outboundEnd() != null) {
            long hours = Duration.between(w.outboundStart(), w.outboundEnd()).toHours();
            window = QuoteFormat.time(w.outboundStart()) + " – " + QuoteFormat.time(w.outboundEnd())
                    + (hours > 0 ? " (" + hours + "시간)" : "");
        }
        String size = w.width() == null || w.length() == null ? "—"
                : oneDecimal(w.width()) + " m × " + oneDecimal(w.length()) + " m · " + comma(Math.round(w.area())) + " m²";
        return new Issue(status.toString(), QuoteFormat.elapsed(d.elapsedSeconds()), model,
                w.name(), size, w.workerCount() == null ? "—" : w.workerCount() + "명", window,
                w.outboundAvg() == null ? "—" : comma(w.outboundAvg()) + "건", "표준 주문 패턴으로 계산");
    }

    // ── 02 ─────────────────────────────────────────────────────────────────

    private Verdict verdict(EstimateDetailResponse d, Run rec, String model) {
        if (rec == null) {
            String reason = d.reasonCode() == null ? "권장 대수를 내지 못했습니다." : REASON_TEXT.get(d.reasonCode());
            return new Verdict(false, model, null, null, null, reason, null, null, null, null, null, null, null, null);
        }
        long budget = d.budgetLimit();
        long cost = rec.totalCost() == null ? 0 : rec.totalCost();
        StringBuilder lead = new StringBuilder();
        lead.append("목표 주문 처리율 ").append(pct(d.targetThroughput())).append(" %를 달성하는 대수 가운데 효율(주문 처리율 × 로봇 가동률)이 가장 높은 구성입니다. ");
        lead.append("예상 구축 비용은 ").append(won(cost)).append("으로 예산 ").append(won(budget)).append(" ")
                .append(cost <= budget ? "이내" : "초과").append("이며");
        if (d.kneeCount() != null && !d.kneeCount().equals(rec.amrCount())) {
            lead.append(", ").append(d.kneeCount()).append("대부터는 로봇을 늘려도 처리량이 거의 늘지 않습니다.");
        } else {
            lead.append(" 이 대수가 효율의 정점입니다.");
        }
        double diff = rec.throughput() - d.targetThroughput();
        String throughputNote = "목표 " + pct(d.targetThroughput()) + " % 대비 " + (diff >= 0 ? "+" : "−") + oneDecimal(Math.abs(diff)) + "p";
        String utilizationNote = "목표 " + pct(d.targetUtilization()) + " % 이상";
        long usedPct = Math.round(cost * 100.0 / budget);
        String costNote = "예산 " + won(budget) + "의 " + usedPct + " %<br>잔여 " + won(Math.max(0, budget - cost));
        String leadTimeNote = rec.kpi() == null || rec.kpi().leadTimeMeanS() == null ? "주문의 90 %가 이 시간 안에 완료"
                : "주문의 90 %가 이 시간 안에 완료<br>평균은 " + minutes(rec.kpi().leadTimeMeanS());
        return new Verdict(true, model, rec.amrCount(), "● 목표 달성 · 예산 이내 · 효율 최고", lead.toString(), null,
                pct(rec.throughput()), throughputNote, pct(rec.utilization()), utilizationNote,
                eok(cost), costNote, rec.leadTimeP90() == null ? "—" : oneDecimal(rec.leadTimeP90() / 60.0), leadTimeNote);
    }

    // ── 03 ─────────────────────────────────────────────────────────────────

    private List<TargetRow> targets(EstimateDetailResponse d, Run rec, WarehouseResponse w) {
        List<TargetRow> rows = new ArrayList<>();
        boolean thrOk = rec.throughput() >= d.targetThroughput();
        String thrNote = w.outboundAvg() != null && rec.outbound() != null
                ? "하루 " + comma(w.outboundAvg()) + "건 중 " + comma(rec.outbound()) + "건 처리" : "접수한 주문 중 처리 완료 비율";
        rows.add(new TargetRow("주문 처리율", pct(d.targetThroughput()) + " % 이상", pct(rec.throughput()) + " %",
                thrOk, thrOk ? "달성" : "미달", thrNote));
        boolean utlOk = rec.utilization() >= d.targetUtilization();
        rows.add(new TargetRow("로봇 가동률", pct(d.targetUtilization()) + " % 이상", pct(rec.utilization()) + " %",
                utlOk, utlOk ? "달성" : "미달", "이동 · 대기 · 상하차로 일한 시간의 비율"));
        long cost = rec.totalCost() == null ? 0 : rec.totalCost();
        boolean costOk = cost <= d.budgetLimit();
        rows.add(new TargetRow("구축 비용", comma(d.budgetLimit()) + " 원 이하", comma(cost) + " 원",
                costOk, costOk ? "예산 이내" : "예산 초과",
                costOk ? "잔여 " + comma(d.budgetLimit() - cost) + " 원" : "초과 " + comma(cost - d.budgetLimit()) + " 원"));
        if (rec.leadTimeP90() != null) {
            Double limit = estimateProperties.leadTimeP90LimitSeconds();
            String note = "접수 주문의 90 %가 " + minutes(rec.leadTimeP90()) + " 안에 처리 완료";
            if (rec.kpi() != null && rec.kpi().leadTimeMeanS() != null) {
                note += " · 평균 " + minutes(rec.kpi().leadTimeMeanS());
            }
            if (limit == null) {
                rows.add(new TargetRow("주문 처리 시간 (90 % 기준)", "판정에 미포함", minutes(rec.leadTimeP90()), null, "— 참고", note));
            } else {
                boolean ok = rec.leadTimeP90() <= limit;
                rows.add(new TargetRow("주문 처리 시간 (90 % 기준)", minutes(limit) + " 이하", minutes(rec.leadTimeP90()),
                        ok, ok ? "달성" : "초과", note));
            }
        }
        return rows;
    }

    // ── 04 ─────────────────────────────────────────────────────────────────

    private Cost cost(EstimateDetailResponse d, Run rec) {
        int n = rec.amrCount();
        long unit = estimateProperties.amrPrice();
        long install = estimateProperties.installPerUnit();
        long total = rec.totalCost() == null ? (unit + install) * n : rec.totalCost();
        long extra = total - (unit + install) * n;
        double used = d.budgetLimit() == 0 ? 0 : total * 100.0 / d.budgetLimit();
        return new Cost(comma(unit), comma(install), n + " 대", comma(unit * n), comma(install * n),
                extra > 0 ? "기타 설비" : null, extra > 0 ? comma(extra) : null,
                comma(total), comma(d.budgetLimit()), Math.min(100.0, Math.round(used * 10) / 10.0), oneDecimal(used),
                comma(Math.max(0, d.budgetLimit() - total)));
    }

    // ── 05 ─────────────────────────────────────────────────────────────────

    private Verification verification(EstimateDetailResponse d, Run rec) {
        EstimateDetailResponse.Verification v = d.verification();
        if (v == null) {
            return null;
        }
        int robots = v.nRobots() == null ? rec.amrCount() : v.nRobots();
        String method = "로봇 " + robots + "대를 3D 물리 시뮬레이션(Isaac Sim)에서 실제 크기와 속도로 재현";
        String window = v.windowS() == null ? "주문이 가장 몰리는 구간" : "주문이 가장 몰리는 " + Math.round(v.windowS() / 60.0) + "분";
        boolean finished = v.notice() != VerifyNoticeCode.NOT_FINISHED;
        String result;
        if (!finished) {
            result = "정상 종료되지 않음" + (v.error() == null ? "" : " · " + v.error());
        } else if (v.notice() == VerifyNoticeCode.PARTIAL_FLEET) {
            result = "정상 완료 · 로봇 " + robots + "대 중 " + v.robotsOnline() + "대 가동";
        } else {
            result = "정상 완료 · 로봇 " + robots + "대 모두 가동";
        }
        List<CompareRow> rows = new ArrayList<>();
        Double leadRatio = null;
        Double conflictDiff = null;
        if (v.comparison() != null) {
            var c = v.comparison();
            rows.add(new CompareRow("시간당 처리 주문",
                    c.throughputOrdersPerH().expected() == null ? "—" : Math.round(c.throughputOrdersPerH().expected()) + "건",
                    c.throughputOrdersPerH().verified() == null ? "—" : Math.round(c.throughputOrdersPerH().verified()) + "건",
                    ratioText(c.throughputOrdersPerH().diff(), c.throughputOrdersPerH().expected()), false));
            leadRatio = ratio(c.leadTimeP90S().diff(), c.leadTimeP90S().expected());
            rows.add(new CompareRow("주문 처리 시간 (90 % 기준)", minutes(c.leadTimeP90S().expected()), minutes(c.leadTimeP90S().verified()),
                    ratioText(c.leadTimeP90S().diff(), c.leadTimeP90S().expected()), leadRatio != null && leadRatio > 0));
            conflictDiff = c.conflictWaitRatio().diff();
            rows.add(new CompareRow("통로 혼잡으로 멈춘 시간", pctOrDash(c.conflictWaitRatio().expected()), pctOrDash(c.conflictWaitRatio().verified()),
                    conflictDiff == null ? "—" : QuoteFormat.signedPoints(conflictDiff), conflictDiff != null && conflictDiff > 0));
        }
        return new Verification(method, window, finished, result, v.comparison() != null, rows,
                noticeText(v, robots, leadRatio));
    }

    private static String noticeText(EstimateDetailResponse.Verification v, int robots, Double leadRatio) {
        String text = switch (v.notice()) {
            case NOT_FINISHED -> "물리 검증이 정상 종료되지 않아 비교 수치가 없습니다.";
            case DIFFERENT_CONDITIONS -> "물리 검증이 계산과 다른 조건에서 돌아 수치를 비교하지 않습니다.";
            case NO_BASELINE -> "비교할 계산 값이 없습니다.";
            case PARTIAL_FLEET -> "로봇 " + robots + "대 중 " + v.robotsOnline() + "대만 가동되었습니다. 검증 결과를 참고용으로만 보세요.";
            case SLOWER_AT_PEAK -> "주문이 몰리는 시간대에는 통로 혼잡이 계산보다 높아 주문 처리 시간이 "
                    + (leadRatio == null || leadRatio <= 0 ? "" : "약 " + Math.round(leadRatio * 100) + " % ") + "길어질 수 있습니다.";
            case MATCHES -> "계산과 물리 검증 결과가 일치합니다.";
        };
        return text + " 권장 대수 판정에는 영향이 없습니다.";
    }

    private static Double ratio(Double diff, Double expected) {
        return diff == null || expected == null || expected == 0 ? null : diff / expected;
    }

    private static String ratioText(Double diff, Double expected) {
        Double r = ratio(diff, expected);
        return r == null ? "—" : QuoteFormat.signedPct(r);
    }

    private static String pctOrDash(Double ratio) {
        return ratio == null ? "—" : ratioPct(ratio) + " %";
    }

    // ── 06 ─────────────────────────────────────────────────────────────────

    /** 권장 · 최소 구성 · 효과 정체 · 양끝 · 예산 경계 앞뒤는 항상, 나머지는 간격을 고르게 채워 최대 12행. */
    static List<Integer> pickRows(List<Integer> counts, Integer recommended, Integer minimal, Integer knee,
                                  Integer firstOverBudget) {
        if (counts.size() <= FLEET_ROWS) {
            return counts;
        }
        TreeSet<Integer> picked = new TreeSet<>();
        picked.add(counts.get(0));
        picked.add(counts.get(counts.size() - 1));
        for (Integer must : Arrays.asList(recommended, minimal, knee, firstOverBudget)) {
            if (must != null && counts.contains(must)) {
                picked.add(must);
            }
        }
        if (firstOverBudget != null) {
            int i = counts.indexOf(firstOverBudget);
            if (i > 0) {
                picked.add(counts.get(i - 1));
            }
        }
        int slots = FLEET_ROWS - picked.size();
        for (int k = 1; k <= slots && picked.size() < FLEET_ROWS; k++) {
            int idx = (int) Math.round(k * (counts.size() - 1) / (double) (slots + 1));
            int j = idx;
            while (j < counts.size() && picked.contains(counts.get(j))) {
                j++;
            }
            if (j < counts.size()) {
                picked.add(counts.get(j));
            }
        }
        return new ArrayList<>(picked);
    }

    private List<FleetRow> fleet(EstimateDetailResponse d, List<Run> done) {
        List<Integer> counts = done.stream().map(Run::amrCount).toList();
        Integer firstOver = done.stream().filter(r -> r.totalCost() != null && r.totalCost() > d.budgetLimit())
                .map(Run::amrCount).findFirst().orElse(null);
        List<Integer> picked = pickRows(counts, d.recommendedCount(), d.minimalCount(), d.kneeCount(), firstOver);
        return done.stream().filter(r -> picked.contains(r.amrCount())).map(r -> new FleetRow(
                r.amrCount(),
                r.amrCount().equals(d.recommendedCount()),
                r.amrCount().equals(d.minimalCount()) && !r.amrCount().equals(d.recommendedCount()),
                r.amrCount().equals(d.kneeCount()) && !r.amrCount().equals(d.recommendedCount()),
                pct(r.throughput()) + " %",
                pct(r.utilization()) + " %",
                targetMet(r, d),
                targetText(r, d),
                r.utilization() == null ? "—" : oneDecimal(efficiency(r)),
                r.outbound() == null ? "—" : comma(r.outbound()) + "건",
                r.totalCost() == null ? "—" : won(r.totalCost()),
                r.totalCost() != null && r.totalCost() > d.budgetLimit())).toList();
    }

    /** 목표는 처리율과 가동률을 <b>둘 다</b> 넘어야 달성이다 — 처리율만 보면 로봇이 노는 구성도 달성으로 읽힌다. */
    private static boolean targetMet(Run r, EstimateDetailResponse d) {
        return r.throughput() >= d.targetThroughput() && r.utilization() >= d.targetUtilization();
    }

    /** 못 넘은 쪽을 이름으로 적는다 — 웹 리포트의 표와 같은 말을 쓴다. */
    private static String targetText(Run r, EstimateDetailResponse d) {
        if (targetMet(r, d)) {
            return "달성";
        }
        List<String> missed = new ArrayList<>();
        if (r.throughput() < d.targetThroughput()) {
            missed.add("처리율");
        }
        if (r.utilization() < d.targetUtilization()) {
            missed.add("가동률");
        }
        return String.join("·", missed) + " 미달";
    }

    /**
     * 최소 구성 한 줄 — 얼마를 아끼는 대신 효율을 얼마나 내주는지. 두 대수가 같으면 더 줄일 여지가 없다는
     * 뜻이라 금액·효율 차이가 없고, 그 사실만 적는다.
     */
    private String minimalNote(EstimateDetailResponse d, Run rec, List<Run> done) {
        if (d.minimalCount() == null) {
            return "";
        }
        if (d.minimalCount().equals(d.recommendedCount())) {
            return "권장이 곧 목표를 만족하는 가장 적은 대수입니다. ";
        }
        Run min = done.stream().filter(r -> d.minimalCount().equals(r.amrCount())).findFirst().orElse(null);
        if (min == null || min.totalCost() == null || rec.totalCost() == null || min.utilization() == null) {
            return "";
        }
        return "최소 구성은 목표를 만족하는 가장 적은 대수로, " + min.amrCount() + "대(" + won(min.totalCost()) + ")는 "
                + "권장보다 " + won(rec.totalCost() - min.totalCost()) + " 적지만 효율 " + oneDecimal(efficiency(min))
                + " %로 권장보다 " + oneDecimal(efficiency(rec) - efficiency(min)) + " %p 안 좋습니다. ";
    }

    private String fleetNote(EstimateDetailResponse d, Run rec, List<Run> done) {
        StringBuilder note = new StringBuilder(
                "효율 점수 = 주문 처리율 × 로봇 가동률 ÷ 100, 주문을 많이 처리하면서 로봇이 놀지 않을수록 높습니다. ");
        if (rec != null) {
            note.append("권장은 목표와 예산을 만족하는 대수 중 효율 점수가 가장 높은 대수입니다");
            List<String> excluded = done.stream()
                    .filter(r -> r.utilization() != null && efficiency(r) > efficiency(rec) && r.throughput() < d.targetThroughput())
                    .map(r -> r.amrCount() + "대").toList();
            if (!excluded.isEmpty()) {
                note.append("(").append(String.join(" · ", excluded)).append("는 처리율 미달로 제외)");
            }
            note.append(". ");
            note.append(minimalNote(d, rec, done));
        }
        note.append("빨간 비용은 예산 초과.");
        if (done.size() > FLEET_ROWS) {
            note.append(" 표에 없는 대수는 웹 리포트에서 볼 수 있습니다.");
        }
        return note.toString();
    }

    private static double efficiency(Run r) {
        return r.throughput() * r.utilization() / 100.0;
    }

    // ── 07 ─────────────────────────────────────────────────────────────────

    private Curve curve(EstimateDetailResponse d, List<Run> done) {
        int min = done.get(0).amrCount();
        int max = done.get(done.size() - 1).amrCount();
        double iw = SVG_W - PAD_L - PAD_R, ih = SVG_H - PAD_T - PAD_B;
        long rawMax = Math.max(d.budgetLimit(), done.stream().mapToLong(r -> r.totalCost() == null ? 0 : r.totalCost()).max().orElse(0));
        long costMax = niceCostMax(rawMax);

        StringBuilder eff = new StringBuilder();
        StringBuilder costPath = new StringBuilder();
        for (int i = 0; i < done.size(); i++) {
            Run r = done.get(i);
            double x = x(r.amrCount(), min, max, iw);
            String cmd = i == 0 ? "M" : "L";
            if (r.utilization() != null) {
                eff.append(eff.isEmpty() ? "M" : "L").append(f(x)).append(' ').append(f(PAD_T + ih - efficiency(r) / 100.0 * ih)).append(' ');
            }
            if (r.totalCost() != null) {
                costPath.append(costPath.isEmpty() ? "M" : "L").append(f(x)).append(' ').append(f(PAD_T + ih - r.totalCost() / (double) costMax * ih)).append(' ');
            }
        }
        List<AxisLabel> yLeft = new ArrayList<>();
        List<AxisLabel> yRight = new ArrayList<>();
        for (int g = 0; g <= 100; g += 25) {
            double y = PAD_T + ih - g / 100.0 * ih;
            yLeft.add(new AxisLabel(y, String.valueOf(g), false));
            yRight.add(new AxisLabel(y, eok(Math.round(costMax * g / 100.0)) + "억", false));
        }
        List<AxisLabel> xLabels = new ArrayList<>();
        int step = Math.max(1, (int) Math.ceil((max - min) / 6.0));
        TreeSet<Integer> ticks = new TreeSet<>();
        for (int n = min; n <= max; n += step) {
            ticks.add(n);
        }
        ticks.add(max);
        if (d.recommendedCount() != null) {
            ticks.add(d.recommendedCount());
        }
        for (int n : ticks) {
            xLabels.add(new AxisLabel(x(n, min, max, iw), n + "대", Integer.valueOf(n).equals(d.recommendedCount())));
        }
        Run rec = d.recommendedCount() == null ? null
                : done.stream().filter(r -> d.recommendedCount().equals(r.amrCount())).findFirst().orElse(null);
        double recX = rec == null ? -1 : x(rec.amrCount(), min, max, iw);
        double recY = rec == null || rec.utilization() == null ? -1 : PAD_T + ih - efficiency(rec) / 100.0 * ih;
        Double kneeX = d.kneeCount() == null || d.kneeCount().equals(d.recommendedCount()) || d.kneeCount() < min || d.kneeCount() > max
                ? null : x(d.kneeCount(), min, max, iw);
        return new Curve(eff.toString().trim(), costPath.toString().trim(), xLabels, yLeft, yRight,
                PAD_T + ih - d.budgetLimit() / (double) costMax * ih, "예산 " + won(d.budgetLimit()),
                kneeX, kneeX == null ? null : d.kneeCount() + "대부터 효과 정체",
                recX, recY, rec == null ? null : "권장 " + rec.amrCount() + "대 · 효율 " + oneDecimal(efficiency(rec)));
    }

    private static double x(int n, int min, int max, double iw) {
        return max == min ? PAD_L + iw / 2 : PAD_L + (n - min) / (double) (max - min) * iw;
    }

    private static String f(double v) {
        return String.format(Locale.ROOT, "%.1f", v);
    }

    /** 비용 축 최대값 — 4등분 눈금이 예쁜 값(0.25·0.5·1·1.5·2·2.5·3·5·7.5·10억 …)이 되게 올린다. 웹 {@code niceCostMax} 와 같다. */
    static long niceCostMax(long rawMax) {
        double[] steps = {0.25, 0.5, 1, 1.5, 2, 2.5, 3, 5, 7.5, 10, 15, 20, 25, 50, 100};
        long eok = 100_000_000L;
        for (double s : steps) {
            if (4 * s * eok >= rawMax) {
                return Math.round(4 * s * eok);
            }
        }
        return (long) Math.ceil(rawMax / (4.0 * eok)) * 4 * eok;
    }

    // ── 08 ─────────────────────────────────────────────────────────────────

    private static Ops ops(Run rec) {
        var k = rec.kpi();
        return new Ops(minutes(k.leadTimeMeanS()), QuoteFormat.seconds(k.queueTimeMeanS()), ratioPct(k.conflictWaitRatio()),
                QuoteFormat.km(k.distanceTotalM()), rec.amrCount() + "대 합산");
    }

    // ── 공통 ────────────────────────────────────────────────────────────────

    private static String modelName(String amrModel) {
        return amrModel == null || amrModel.isBlank() ? "iw.hub" : amrModel;
    }

    private static String loadLogo() {
        try {
            byte[] png = new ClassPathResource("quote/santafactory-logo.png").getContentAsByteArray();
            return "data:image/png;base64," + Base64.getEncoder().encodeToString(png);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }
}
