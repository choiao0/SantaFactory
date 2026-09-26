package com.ssafy.santafactory.service.estimate.quote;

import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse.Run;
import com.ssafy.santafactory.dto.estimate.VerifyNoticeCode;
import com.ssafy.santafactory.dto.simulation.PhysicsMetrics;
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
    static final int FLEET_ROWS = 10;

    /** 보고서(3~5쪽)가 붙으면 전체 쪽 수. */
    static final int PAGES_WITH_REPORT = 5;
    static final int PAGES_QUOTE_ONLY = 2;

    static final double SVG_W = 672, SVG_H = 112, PAD_L = 36, PAD_R = 48, PAD_T = 14, PAD_B = 22;

    /** 이 처리율부터는 하루 주문을 다 뺀 것으로 본다. */
    private static final double FULL_THROUGHPUT = 99.95;

    private static final Map<ReasonCode, String> REASON_TEXT = new EnumMap<>(Map.of(
            ReasonCode.BUDGET_EXCEEDED, "예산 안에서 도입할 수 있는 로봇 대수가 없습니다. 예산을 늘리거나 목표를 낮춰 다시 요청해 주세요.",
            ReasonCode.THROUGHPUT_SHORT, "예산 안의 대수로는 목표 주문 처리율을 달성할 수 없습니다. 목표를 낮추거나 예산을 늘려 다시 요청해 주세요.",
            ReasonCode.UTILIZATION_SHORT, "목표 주문 처리율을 달성하는 대수에서는 로봇 가동률이 목표에 미치지 못합니다. 로봇 가동률 목표를 조정해 다시 요청해 주세요.",
            ReasonCode.LEAD_TIME_LONG, "목표 주문 처리율은 달성하지만 주문 처리 시간이 기준을 넘습니다. 로봇 대수를 늘리거나 주문 처리 시간 기준을 조정해 주세요.",
            ReasonCode.ALL_FAILED, "대수별 시뮬레이션을 완료하지 못해 권장 대수를 산정하지 못했습니다. 조건을 확인한 뒤 다시 요청해 주세요.",
            ReasonCode.LOAD_TOO_LOW, "주문량이 적어 모든 대수의 주문 처리율이 100%입니다. 대수 간 차이가 없어 권장 대수를 산정하지 않았습니다."));

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
        QuoteReport report = rec == null ? null : QuoteReports.build(d, w, done, rec, estimateProperties);
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
                logoDataUri,
                physicsLimitLine(d),
                report,
                report == null ? PAGES_QUOTE_ONLY : PAGES_WITH_REPORT);
    }

    // ── 05 · 17 — 대수별 3D 주행 검증 (S15P21A106-244 · 280: 대수별 표는 보고서 17로 옮겼다) ──

    static long contactCount(PhysicsMetrics p) {
        return (p.robotContacts() == null ? 0 : p.robotContacts()) + (p.rackContacts() == null ? 0 : p.rackContacts());
    }

    /** 명세 §D 한글 라벨 — 화면과 같은 말을 쓴다. */
    static String verdictLabel(String verdict) {
        return switch (verdict) {
            case "PASS" -> "적합";
            case "WARN" -> "주의";
            case "FAIL" -> "부적합";
            default -> "판정 불가";
        };
    }

    /** 검증한 대수가 있을 때만 한 줄을 낸다 — 통과한 대수가 없으면 그 사실을 적는다. */
    static String physicsLimitLine(EstimateDetailResponse d) {
        if (d.physicsLimit() != null) {
            return d.physicsLimit() + "대까지 3D 주행 검증을 통과했습니다.";
        }
        return d.verifications().isEmpty() ? null : "아직 3D 주행 검증을 통과한 대수가 없습니다.";
    }

    // ── 01 ─────────────────────────────────────────────────────────────────

    private Issue issue(EstimateDetailResponse d, WarehouseResponse w, String model) {
        StringBuilder status = new StringBuilder(d.status() == EstimateStatus.PARTIAL ? "일부 완료" : "완료");
        status.append(" · 대수별 시뮬레이션 ").append(d.runs().size()).append("회");
        if (d.verification() != null && d.verification().notice() != VerifyNoticeCode.NOT_FINISHED) {
            status.append(" · 3D 주행 검증 완료");
        }
        String window = "—";
        if (w.outboundStart() != null && w.outboundEnd() != null) {
            long hours = Duration.between(w.outboundStart(), w.outboundEnd()).toHours();
            window = QuoteFormat.time(w.outboundStart()) + " – " + QuoteFormat.time(w.outboundEnd())
                    + (hours > 0 ? " (" + hours + "시간)" : "");
        }
        String size = w.width() == null || w.length() == null ? "—"
                : oneDecimal(w.width()) + " m × " + oneDecimal(w.length()) + " m · " + comma(Math.round(w.area())) + " m²";
        return new Issue(status.toString(), model,
                w.name(), size, w.workerCount() == null ? "—" : w.workerCount() + "명", window,
                w.outboundAvg() == null ? "—" : comma(w.outboundAvg()) + "건", "일반적인 시간대별 주문 분포를 적용했습니다.");
    }

    // ── 02 ─────────────────────────────────────────────────────────────────

    private Verdict verdict(EstimateDetailResponse d, Run rec, String model) {
        if (rec == null) {
            String reason = d.reasonCode() == null ? "권장 대수를 산정하지 못했습니다." : REASON_TEXT.get(d.reasonCode());
            return new Verdict(false, model, null, null, null, reason, null, null, null, null, null, null, null, null);
        }
        long budget = d.budgetLimit();
        long cost = rec.totalCost() == null ? 0 : rec.totalCost();
        StringBuilder lead = new StringBuilder();
        lead.append("목표 주문 처리율 ").append(pct(d.targetThroughput())).append("%를 달성하는 대수 가운데 운영 효율이 가장 높은 구성입니다. ");
        lead.append("예상 구축 비용은 ").append(won(cost)).append("으로 예산 ").append(won(budget)).append(" ")
                .append(cost <= budget ? "이내" : "초과").append("입니다.");
        if (d.kneeCount() != null && !d.kneeCount().equals(rec.amrCount())) {
            lead.append(" ").append(d.kneeCount()).append("대부터는 로봇을 늘려도 주문 처리량이 거의 늘지 않습니다.");
        } else {
            lead.append(" 비교한 모든 대수 가운데 이 대수에서 운영 효율이 가장 높습니다.");
        }
        double diff = rec.throughput() - d.targetThroughput();
        String throughputNote = "목표 " + pct(d.targetThroughput()) + "% 대비 " + (diff >= 0 ? "+" : "−") + oneDecimal(Math.abs(diff)) + "%p";
        String utilizationNote = "목표 " + pct(d.targetUtilization()) + "% 이상";
        long usedPct = Math.round(cost * 100.0 / budget);
        String costNote = "예산 " + won(budget) + "의 " + usedPct + "%<br>잔여 " + won(Math.max(0, budget - cost));
        String leadTimeNote = rec.kpi() == null || rec.kpi().leadTimeMeanS() == null ? "주문의 90%가 이 시간 안에 완료"
                : "주문의 90%가 이 시간 안에 완료<br>평균 " + minutes(rec.kpi().leadTimeMeanS());
        return new Verdict(true, model, rec.amrCount(), "● 목표 달성 · 예산 이내 · 운영 효율 최고", lead.toString(), null,
                pct(rec.throughput()), throughputNote, pct(rec.utilization()), utilizationNote,
                eok(cost), costNote, rec.leadTimeP90() == null ? "—" : oneDecimal(rec.leadTimeP90() / 60.0), leadTimeNote);
    }

    // ── 03 ─────────────────────────────────────────────────────────────────

    private List<TargetRow> targets(EstimateDetailResponse d, Run rec, WarehouseResponse w) {
        List<TargetRow> rows = new ArrayList<>();
        boolean thrOk = rec.throughput() >= d.targetThroughput();
        String thrNote = w.outboundAvg() != null && rec.outbound() != null
                ? "하루 " + comma(w.outboundAvg()) + "건 중 " + comma(rec.outbound()) + "건 처리" : "접수한 주문 중 처리 완료 비율";
        rows.add(new TargetRow("주문 처리율", pct(d.targetThroughput()) + "% 이상", pct(rec.throughput()) + "%",
                thrOk, thrOk ? "달성" : "미달", thrNote));
        boolean utlOk = rec.utilization() >= d.targetUtilization();
        rows.add(new TargetRow("로봇 가동률", pct(d.targetUtilization()) + "% 이상", pct(rec.utilization()) + "%",
                utlOk, utlOk ? "달성" : "미달", "이동 · 대기 · 상하차로 일한 시간의 비율"));
        long cost = rec.totalCost() == null ? 0 : rec.totalCost();
        boolean costOk = cost <= d.budgetLimit();
        rows.add(new TargetRow("구축 비용", comma(d.budgetLimit()) + " 원 이하", comma(cost) + " 원",
                costOk, costOk ? "예산 이내" : "예산 초과",
                costOk ? "잔여 " + comma(d.budgetLimit() - cost) + " 원" : "초과 " + comma(cost - d.budgetLimit()) + " 원"));
        if (rec.leadTimeP90() != null) {
            Double limit = estimateProperties.leadTimeP90LimitSeconds();
            String note = "접수 주문의 90%가 " + minutes(rec.leadTimeP90()) + " 안에 처리 완료";
            if (rec.kpi() != null && rec.kpi().leadTimeMeanS() != null) {
                note += " · 평균 " + minutes(rec.kpi().leadTimeMeanS());
            }
            if (limit == null) {
                rows.add(new TargetRow("주문 처리 시간 (90% 기준)", "판정에 미포함", minutes(rec.leadTimeP90()), null, "참고", note));
            } else {
                boolean ok = rec.leadTimeP90() <= limit;
                rows.add(new TargetRow("주문 처리 시간 (90% 기준)", minutes(limit) + " 이하", minutes(rec.leadTimeP90()),
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
        return new Cost(comma(unit), comma(install), n + "대", comma(unit * n), comma(install * n),
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
        String method = "로봇 " + robots + "대를 실제 크기와 속도로 3D 창고에서 주행";
        // 대수마다 작업이 가장 많이 끝난 10분을 고른다 — 주문이 몰린 시각이 아니다 (S15P21A106-280, 보고서 17과 같은 이름)
        String window = v.windowS() == null ? "피크 작업 구간" : "피크 작업 " + Math.round(v.windowS() / 60.0) + "분";
        boolean finished = v.notice() != VerifyNoticeCode.NOT_FINISHED;
        String result;
        if (!finished) {
            // 원인(v.error)은 DB·로그에 남아 있다 — 문서에는 내부 오류 문구를 싣지 않는다
            result = "검증을 완료하지 못했습니다.";
        } else if (v.notice() == VerifyNoticeCode.PARTIAL_FLEET) {
            result = "완료 · 로봇 " + robots + "대 중 " + v.robotsOnline() + "대 가동";
        } else {
            result = "완료 · 로봇 " + robots + "대 모두 가동";
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
            rows.add(new CompareRow("주문 처리 시간 (90% 기준)", minutes(c.leadTimeP90S().expected()), minutes(c.leadTimeP90S().verified()),
                    ratioText(c.leadTimeP90S().diff(), c.leadTimeP90S().expected()), leadRatio != null && leadRatio > 0));
            conflictDiff = c.conflictWaitRatio().diff();
            rows.add(new CompareRow("혼잡 대기 비율", pctOrDash(c.conflictWaitRatio().expected()), pctOrDash(c.conflictWaitRatio().verified()),
                    conflictDiff == null ? "—" : QuoteFormat.signedPoints(conflictDiff), conflictDiff != null && conflictDiff > 0));
        }
        return new Verification(method, window, finished, result, v.comparison() != null, rows,
                noticeText(v, robots, leadRatio));
    }

    /** 주문이 몰릴 때 느려진다는 안내는 그 자체로 끝낸다 — 산정 근거 문장을 덧붙이면 경고가 흐려진다. */
    private static String noticeText(EstimateDetailResponse.Verification v, int robots, Double leadRatio) {
        String text = switch (v.notice()) {
            case NOT_FINISHED -> "3D 주행 검증을 완료하지 못해 비교할 수치가 없습니다.";
            case DIFFERENT_CONDITIONS -> "3D 주행 검증이 시뮬레이션과 다른 조건에서 진행되어 수치를 비교하지 않았습니다.";
            case NO_BASELINE -> "비교할 시뮬레이션 결과가 없습니다.";
            case PARTIAL_FLEET -> "로봇 " + robots + "대 중 " + v.robotsOnline() + "대만 가동되어 검증 결과는 참고용입니다.";
            case SLOWER_AT_PEAK -> "주문이 몰리는 시간에는 혼잡 대기가 시뮬레이션보다 많아 주문 처리 시간이 "
                    + (leadRatio == null || leadRatio <= 0 ? "" : "약 " + Math.round(leadRatio * 100) + "% ") + "길어질 수 있습니다.";
            case MATCHES -> "시뮬레이션과 3D 주행 검증 결과가 일치합니다.";
        };
        return v.notice() == VerifyNoticeCode.SLOWER_AT_PEAK ? text : text + " 권장 대수는 대수별 시뮬레이션 결과로 산정했습니다.";
    }

    private static Double ratio(Double diff, Double expected) {
        return diff == null || expected == null || expected == 0 ? null : diff / expected;
    }

    private static String ratioText(Double diff, Double expected) {
        Double r = ratio(diff, expected);
        return r == null ? "—" : QuoteFormat.signedPct(r);
    }

    private static String pctOrDash(Double ratio) {
        return ratio == null ? "—" : ratioPct(ratio) + "%";
    }

    // ── 06 ─────────────────────────────────────────────────────────────────

    /** 권장 · 최소 구성 · 효과 정체 · 양끝 · 예산 경계 앞뒤는 항상, 나머지는 간격을 고르게 채워 최대 12행. */
    static List<Integer> pickRows(List<Integer> counts, Integer recommended, Integer minimal, Integer knee,
                                  Integer firstOverBudget) {
        return pickRows(counts, recommended, minimal, knee, firstOverBudget, FLEET_ROWS);
    }

    /** {@code limit} 행까지 — 보고서의 서비스 수준 표(S15P21A106-280)는 한 쪽을 다 쓰므로 더 많이 싣는다. */
    static List<Integer> pickRows(List<Integer> counts, Integer recommended, Integer minimal, Integer knee,
                                  Integer firstOverBudget, int limit) {
        if (counts.size() <= limit) {
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
        int slots = limit - picked.size();
        for (int k = 1; k <= slots && picked.size() < limit; k++) {
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
        Integer fullCount = done.stream().filter(r -> r.throughput() >= FULL_THROUGHPUT)
                .map(Run::amrCount).findFirst().orElse(null);
        // 표식이 겹치면 권장만 남긴다 — 한 행에 이름이 둘 이상 붙으면 어느 기준으로 고른 대수인지가 흐려진다
        return done.stream().filter(r -> picked.contains(r.amrCount())).map(r -> new FleetRow(
                r.amrCount(),
                r.amrCount().equals(d.recommendedCount()),
                r.amrCount().equals(d.minimalCount()) && !r.amrCount().equals(d.recommendedCount()),
                r.amrCount().equals(fullCount) && !r.amrCount().equals(d.recommendedCount()),
                r.amrCount().equals(d.kneeCount()) && !r.amrCount().equals(d.recommendedCount()),
                pct(r.throughput()) + "%",
                pct(r.utilization()) + "%",
                targetMet(r, d),
                targetText(r, d),
                r.utilization() == null ? "—" : oneDecimal(efficiency(r)) + "%",
                r.outbound() == null ? "—" : comma(r.outbound()) + "건",
                r.totalCost() == null ? "—" : won(r.totalCost()),
                r.totalCost() != null && r.totalCost() > d.budgetLimit())).toList();
    }

    /** 목표는 처리율과 가동률을 <b>둘 다</b> 넘어야 달성이다 — 처리율만 보면 로봇이 노는 구성도 달성으로 읽힌다. */
    static boolean targetMet(Run r, EstimateDetailResponse d) {
        return r.throughput() >= d.targetThroughput() && r.utilization() >= d.targetUtilization();
    }

    /** 못 넘은 쪽을 이름으로 적는다 — 견적 결과 화면의 표와 같은 말을 쓴다. */
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
            return "권장 대수가 목표를 만족하는 가장 적은 대수입니다. ";
        }
        Run min = done.stream().filter(r -> d.minimalCount().equals(r.amrCount())).findFirst().orElse(null);
        if (min == null || min.totalCost() == null || rec.totalCost() == null || min.utilization() == null) {
            return "";
        }
        return "목표를 만족하는 가장 적은 대수인 " + min.amrCount() + "대(최소 구성)는 " + won(min.totalCost()) + "으로 "
                + "권장 대수보다 " + won(rec.totalCost() - min.totalCost()) + " 적지만, 운영 효율이 "
                + oneDecimal(efficiency(rec) - efficiency(min)) + "%p 낮습니다. ";
    }

    private String fleetNote(EstimateDetailResponse d, Run rec, List<Run> done) {
        StringBuilder note = new StringBuilder(
                "운영 효율은 주문 처리율과 로봇 가동률을 곱한 값으로, 로봇이 쉬는 시간이 적을수록 높습니다. ");
        if (rec != null) {
            note.append("권장 대수는 목표와 예산을 만족하는 대수 가운데 운영 효율이 가장 높은 대수입니다. ");
            List<String> excluded = done.stream()
                    .filter(r -> r.utilization() != null && efficiency(r) > efficiency(rec) && r.throughput() < d.targetThroughput())
                    .map(r -> r.amrCount() + "대").toList();
            if (!excluded.isEmpty()) {
                note.append(String.join(" · ", excluded)).append("는 운영 효율이 더 높지만 주문 처리율이 목표에 미달해 제외했습니다. ");
            }
            note.append(minimalNote(d, rec, done));
        }
        note.append("빨간색 금액은 예산을 초과한 구성입니다.");
        if (done.size() > FLEET_ROWS) {
            note.append(" 표에 없는 대수는 견적 결과 화면에서 확인할 수 있습니다.");
        }
        return note.toString();
    }

    static double efficiency(Run r) {
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
        StringBuilder thr = new StringBuilder();
        StringBuilder costPath = new StringBuilder();
        List<QuoteDocument.Point> points = new ArrayList<>();
        for (Run r : done) {
            double x = x(r.amrCount(), min, max, iw);
            if (r.utilization() != null) {
                double effY = PAD_T + ih - efficiency(r) / 100.0 * ih;
                double thrY = PAD_T + ih - r.throughput() / 100.0 * ih;
                eff.append(eff.isEmpty() ? "M" : "L").append(f(x)).append(' ').append(f(effY)).append(' ');
                thr.append(thr.isEmpty() ? "M" : "L").append(f(x)).append(' ').append(f(thrY)).append(' ');
                points.add(new QuoteDocument.Point(x, effY, thrY, targetMet(r, d)));
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
        Run fullRun = done.stream().filter(r -> r.utilization() != null && r.throughput() >= FULL_THROUGHPUT)
                .findFirst().orElse(null);
        Integer fullCount = fullRun == null ? null : fullRun.amrCount();
        int step = Math.max(1, (int) Math.ceil((max - min) / 6.0));
        TreeSet<Integer> ticks = new TreeSet<>();
        for (int n = min; n <= max; n += step) {
            ticks.add(n);
        }
        ticks.add(max);
        for (Integer keep : Arrays.asList(d.recommendedCount(), d.minimalCount(), fullCount)) {
            if (keep != null) {
                ticks.add(keep);
            }
        }
        List<AxisLabel> xLabels = new ArrayList<>();
        List<AxisLabel> xLabelsThr = new ArrayList<>();
        for (int n : ticks) {
            double xs = x(n, min, max, iw);
            xLabels.add(new AxisLabel(xs, n + "대", Integer.valueOf(n).equals(d.recommendedCount())));
            xLabelsThr.add(new AxisLabel(xs, n + "대",
                    Integer.valueOf(n).equals(fullCount != null ? fullCount : d.recommendedCount())));
        }
        Run rec = d.recommendedCount() == null ? null
                : done.stream().filter(r -> d.recommendedCount().equals(r.amrCount())).findFirst().orElse(null);
        double recX = rec == null ? -1 : x(rec.amrCount(), min, max, iw);
        double recY = rec == null || rec.utilization() == null ? -1 : PAD_T + ih - efficiency(rec) / 100.0 * ih;
        Run minRun = d.minimalCount() == null || d.minimalCount().equals(d.recommendedCount()) ? null
                : done.stream().filter(r -> d.minimalCount().equals(r.amrCount()) && r.utilization() != null)
                        .findFirst().orElse(null);
        String minLabel = minRun == null ? null : "최소 구성 " + minRun.amrCount() + "대";
        QuoteDocument.Mark minimal = minRun == null ? null : mark(
                x(minRun.amrCount(), min, max, iw), PAD_T + ih - efficiency(minRun) / 100.0 * ih, minLabel);
        // 같은 대수라도 두 그림에서 점 높이가 다르다 — 처리율 그림용 자리를 따로 잡는다
        QuoteDocument.Mark minimalThr = minRun == null ? null : mark(
                x(minRun.amrCount(), min, max, iw), PAD_T + ih - minRun.throughput() / 100.0 * ih, minLabel);
        /*
         * 처리율 그림의 빨간 표식 — 하루 주문을 다 빼는 첫 대수(전량 처리). 어느 대수도 100 %에 닿지
         * 않는 견적에는 그 점이 없으므로 대신 권장을 찍는다. 표식이 최소 구성 하나뿐이면 그 대수가 왜
         * 최소인지 견줄 데가 없다.
         */
        Run peakRun = fullRun != null ? fullRun : rec;
        QuoteDocument.Mark thrPeak = peakRun == null || peakRun.utilization() == null
                || (minRun != null && peakRun.amrCount().equals(minRun.amrCount()))
                ? null
                : mark(x(peakRun.amrCount(), min, max, iw), PAD_T + ih - peakRun.throughput() / 100.0 * ih,
                        (fullRun != null ? "전량 처리 " : "권장 ") + peakRun.amrCount() + "대");

        return new Curve(eff.toString().trim(), thr.toString().trim(), costPath.toString().trim(), points,
                SVG_H, PAD_T + ih, SVG_H - PAD_B + 14,
                xLabels, xLabelsThr, yLeft, yRight,
                PAD_T + ih - d.budgetLimit() / (double) costMax * ih, "예산 " + won(d.budgetLimit()),
                recX, recY,
                rec == null ? null : "권장 " + rec.amrCount() + "대 · 운영 효율 " + oneDecimal(efficiency(rec)) + "%",
                minimal, minimalThr, thrPeak);
    }

    /** 표식 하나 — 이름은 그림에 쓰지 않고 범례가 말한다 (S15P21A106-271). */
    private static QuoteDocument.Mark mark(double x, double y, String label) {
        return new QuoteDocument.Mark(x, y, label);
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
        // 옆칸(평균 주문 처리 시간)이 분이라, 초로 적으면 2935초처럼 한눈에 비교가 안 된다
        return new Ops(minutes(k.leadTimeMeanS()), minutes(k.queueTimeMeanS()), ratioPct(k.conflictWaitRatio()),
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
