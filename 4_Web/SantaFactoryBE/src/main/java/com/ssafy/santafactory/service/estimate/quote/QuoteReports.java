package com.ssafy.santafactory.service.estimate.quote;

import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse.Run;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse.VerificationRun;
import com.ssafy.santafactory.dto.simulation.PhysicsMetrics;
import com.ssafy.santafactory.dto.warehouse.WarehouseResponse;
import com.ssafy.santafactory.service.estimate.EstimateProperties;
import com.ssafy.santafactory.service.estimate.PhysicsVerdict;
import com.ssafy.santafactory.service.estimate.quote.QuoteDocument.AxisLabel;
import com.ssafy.santafactory.service.estimate.quote.QuoteReport.GainBar;
import com.ssafy.santafactory.service.estimate.quote.QuoteReport.GainChart;
import com.ssafy.santafactory.service.estimate.quote.QuoteReport.MarginalRow;
import com.ssafy.santafactory.service.estimate.quote.QuoteReport.PeakRow;
import com.ssafy.santafactory.service.estimate.quote.QuoteReport.ServiceRow;
import com.ssafy.santafactory.service.estimate.quote.QuoteReport.WaitBar;
import com.ssafy.santafactory.service.estimate.quote.QuoteReport.WaitChart;

import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

import static com.ssafy.santafactory.service.estimate.quote.QuoteFormat.comma;
import static com.ssafy.santafactory.service.estimate.quote.QuoteFormat.minutes;
import static com.ssafy.santafactory.service.estimate.quote.QuoteFormat.oneDecimal;
import static com.ssafy.santafactory.service.estimate.quote.QuoteFormat.pct;
import static com.ssafy.santafactory.service.estimate.quote.QuoteFormat.ratioPct;
import static com.ssafy.santafactory.service.estimate.quote.QuoteFormat.won;

/**
 * 견적서 3~5쪽 「도입 검토 보고서」 값 (S15P21A106-280). 문장은 숫자에서 만든다 — 조건이 맞지 않는 문장은 싣지 않는다.
 * 고객 문서라 내부 용어(시뮬 엔진 이름·run·창 등)를 쓰지 않고, 화면·1~2쪽과 같은 말을 쓴다.
 */
final class QuoteReports {

    /** 14 대수별 서비스 수준 표 행 수 — 표와 15 그래프가 한 쪽에 같이 들어가는 최대치. */
    static final int SERVICE_ROWS = 14;
    /** 17 표 행 수 — 5쪽에 16 · 18 과 함께 들어가는 최대치. 권장 대수에 가까운 대수부터 싣는다. */
    static final int PEAK_ROWS = 6;
    /** 누적 막대 두 칸 사이의 바탕색 틈(px). */
    static final double GAP = 2;

    static final double W = 672, PAD_L = 40, PAD_R = 12, PAD_T = 14, PAD_B = 22;
    static final double WAIT_H = 150, GAIN_H = 118;

    /** 이 가동률(%)부터는 여유가 거의 없다고 적는다. */
    private static final double SATURATED_UTILIZATION = 97.0;
    /** 3D 주행 계획 대비 수행률이 이보다 낮으면 위험으로 적는다. */
    private static final double RATIO_RISK = 0.95;
    /** 평균 주문 처리 시간 중 배정 대기 몫 — 이 이상이면 로봇 수가 처리 시간을 좌우한다고 적는다. */
    private static final double QUEUE_DOMINANT = 0.5;
    private static final double QUEUE_RISK = 0.8;
    /** 시간당 처리량이 이만큼도 안 늘면 1건당 비용을 적지 않는다. */
    private static final double MIN_GAIN = 0.05;
    private static final double[] MINUTE_STEPS = {0.5, 1, 2, 5, 10, 15, 20, 30, 60, 120, 180, 240, 480};
    private static final double[] GAIN_TOPS = {1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000};
    private static final DateTimeFormatter HH_MM = DateTimeFormatter.ofPattern("HH:mm");

    private QuoteReports() {
    }

    static QuoteReport build(EstimateDetailResponse d, WarehouseResponse w, List<Run> done, Run rec, EstimateProperties props) {
        Map<Integer, VerificationRun> checks = d.verifications().stream()
                .collect(Collectors.toMap(VerificationRun::nRobots, Function.identity(), (a, b) -> a));
        Map<Integer, Double> gains = gains(done);
        Run up = next(done, rec);
        List<Run> rows = serviceRuns(d, done);
        return new QuoteReport(
                basis(d, done, rec, gains, checks),
                up == null ? null : alternativeTitle(rec, up),
                up == null ? null : alternative(rec, up, checks),
                method(done, w, props),
                rows.stream().map(r -> serviceRow(d, r)).toList(),
                serviceNote(w, props),
                waitChart(rows, rec),
                waitNote(rows),
                gainChart(done, rec, d.kneeCount(), gains),
                marginalRows(done, rec, gains),
                marginalNote(done, rec, d.kneeCount(), gains),
                peakRuns(d).stream().map(v -> peakRow(v, d.recommendedCount(), w.outboundStart())).toList(),
                peakNote(d.verifications().size() > PEAK_ROWS),
                risks(rec, up, checks),
                assumptions(w, props));
    }

    // ── 11 판단 근거 ──────────────────────────────────────────────────────────

    private static List<String> basis(EstimateDetailResponse d, List<Run> done, Run rec, Map<Integer, Double> gains,
                                      Map<Integer, VerificationRun> checks) {
        List<String> out = new ArrayList<>();
        out.add(ruleLine(d, done, rec));
        addIfPresent(out, kneeLine(d, done, rec, gains));
        addIfPresent(out, waitLine(rec));
        addIfPresent(out, checkLine(d, rec, checks));
        return List.copyOf(out);
    }

    private static String ruleLine(EstimateDetailResponse d, List<Run> done, Run rec) {
        StringBuilder s = new StringBuilder("목표 주문 처리율 ").append(pct(d.targetThroughput())).append("%와 로봇 가동률 ")
                .append(pct(d.targetUtilization())).append("%를 충족하고 예산 안에 드는 대수 중 운영 효율이 가장 높은 ")
                .append(rec.amrCount()).append("대를 권장합니다.");
        Run below = previous(done, rec);
        if (below == null) {
            return s.toString();
        }
        String who = (rec.amrCount() - below.amrCount() == 1 ? " 한 대 적은 " : " ") + below.amrCount() + "대";
        if (below.throughput() < d.targetThroughput()) {
            s.append(who).append("는 주문 처리율이 ").append(pct(below.throughput())).append("%로 목표 ")
                    .append(pct(d.targetThroughput())).append("%에 못 미칩니다.");
        } else if (below.utilization() == null || below.utilization() < d.targetUtilization()) {
            s.append(who).append("는 로봇 가동률이 ").append(pct(below.utilization())).append("%로 목표 ")
                    .append(pct(d.targetUtilization())).append("%에 못 미칩니다.");
        } else if (below.totalCost() != null && below.totalCost() > d.budgetLimit()) {
            s.append(who).append("는 구축 비용이 예산을 넘습니다.");
        } else if (rec.utilization() != null) {
            s.append(who).append("도 목표는 충족하지만 운영 효율이 ").append(oneDecimal(QuoteDocumentFactory.efficiency(below)))
                    .append("%로 ").append(rec.amrCount()).append("대(").append(oneDecimal(QuoteDocumentFactory.efficiency(rec)))
                    .append("%)보다 낮습니다.");
        }
        return s.toString();
    }

    private static String kneeLine(EstimateDetailResponse d, List<Run> done, Run rec, Map<Integer, Double> gains) {
        Run knee = d.kneeCount() == null ? null : find(done, d.kneeCount());
        if (knee == null) {
            return null;
        }
        if (knee.amrCount().equals(rec.amrCount())) {
            return "권장 " + knee.amrCount() + "대가 증설 효과 둔화 지점입니다. 이보다 늘려도 주문 처리량이 거의 늘지 않습니다.";
        }
        String head = knee.amrCount() + "대부터는 로봇을 늘려도 주문 처리량이 거의 늘지 않습니다(증설 효과 둔화 지점).";
        Run before = previous(done, knee);
        Double gain = gains.get(knee.amrCount());
        if (before == null || gain == null) {
            return head;
        }
        String step = before.amrCount() + "→" + knee.amrCount() + "대는 ";
        String tail = gain <= MIN_GAIN ? step + "처리량이 늘지 않습니다." : step + oneDecimal(round1(gain)) + "건만 늘어납니다.";
        Run earlier = previous(done, before);
        Double earlierGain = gains.get(before.amrCount());
        if (earlier != null && earlierGain != null && earlierGain > MIN_GAIN) {
            return head + " " + earlier.amrCount() + "→" + before.amrCount() + "대는 시간당 " + oneDecimal(round1(earlierGain))
                    + "건이 늘어나지만 " + tail;
        }
        return head + " 시간당 처리량은 " + tail;
    }

    private static String waitLine(Run rec) {
        Double lead = rec.kpi() == null ? null : rec.kpi().leadTimeMeanS();
        Double queue = rec.kpi() == null ? null : rec.kpi().queueTimeMeanS();
        if (lead == null || queue == null || lead <= 0) {
            return null;
        }
        double share = queue / lead;
        String head = "권장 " + rec.amrCount() + "대의 평균 주문 처리 시간 " + minutes(lead) + " 중 ";
        if (share >= QUEUE_DOMINANT) {
            return head + minutes(queue) + "(" + share(share) + ")은 로봇 배정을 기다린 시간입니다. 주문 처리 시간은 로봇 수에 크게 좌우됩니다.";
        }
        return head + "로봇 배정 대기는 " + minutes(queue) + "(" + share(share) + ")이고, 나머지는 이동과 작업 시간입니다.";
    }

    private static String checkLine(EstimateDetailResponse d, Run rec, Map<Integer, VerificationRun> checks) {
        if (checks.isEmpty()) {
            return null;
        }
        VerificationRun v = checks.get(rec.amrCount());
        Double ratio = ratio(v);
        String head;
        if (v == null) {
            head = "권장 " + rec.amrCount() + "대는 아직 3D 주행 검증을 하지 않았습니다.";
        } else if ("FAILED".equals(v.status())) {
            head = "권장 " + rec.amrCount() + "대의 3D 주행 검증은 끝까지 진행되지 못했습니다.";
        } else if (ratio == null) {
            head = "권장 " + rec.amrCount() + "대의 3D 주행 검증 결과를 기다리고 있습니다.";
        } else {
            head = "권장 " + rec.amrCount() + "대는 3D 주행 검증에서 " + QuoteDocumentFactory.verdictLabel(v.verdict())
                    + " 판정을 받았습니다. 피크 작업 10분 동안 계획한 이동과 작업의 " + ratioPct(ratio) + "%를 제시간에 시작했고 "
                    + contactsText(v.physics()) + ".";
        }
        // 통과 상한이 권장과 같으면 같은 말을 되풀이하게 된다 — 다를 때만 붙인다
        boolean limitIsRec = rec.amrCount().equals(d.physicsLimit());
        String limit = QuoteDocumentFactory.physicsLimitLine(d);
        return limit == null || limitIsRec ? head : head + " " + limit;
    }

    // ── 11 한 대 더 두는 경우 ─────────────────────────────────────────────────

    private static String alternativeTitle(Run rec, Run up) {
        int more = up.amrCount() - rec.amrCount();
        return (more == 1 ? "한 대" : more + "대") + " 더 두는 경우 (" + up.amrCount() + "대)";
    }

    private static String alternative(Run rec, Run up, Map<Integer, VerificationRun> checks) {
        // 조사를 숫자 단위에 묶는다 — "%로", "분으로" (값에 따라 조사가 바뀌지 않게)
        StringBuilder s = new StringBuilder().append(up.amrCount()).append("대로 늘리면 구축 비용이 ")
                .append(won(cost(up) - cost(rec))).append(" 늘어나고, 주문 처리율은 ")
                .append(pct(rec.throughput())).append("%에서 ").append(pct(up.throughput())).append("%로, 로봇 가동률은 ")
                .append(pct(rec.utilization())).append("%에서 ").append(pct(up.utilization())).append("%로");
        Double leadRec = rec.kpi() == null ? null : rec.kpi().leadTimeMeanS();
        Double leadUp = up.kpi() == null ? null : up.kpi().leadTimeMeanS();
        if (leadRec != null && leadUp != null) {
            s.append(", 평균 주문 처리 시간은 ").append(minutes(leadRec)).append("에서 ").append(minutes(leadUp)).append("으로");
        }
        s.append(" 바뀝니다.");
        Double r1 = ratio(checks.get(rec.amrCount()));
        VerificationRun upCheck = checks.get(up.amrCount());
        Double r2 = ratio(upCheck);
        if (r1 != null && r2 != null && r2 < r1) {
            s.append(" 다만 3D 주행 검증에서는 ").append(up.amrCount()).append("대가 ")
                    .append(QuoteDocumentFactory.verdictLabel(upCheck.verdict())).append(" 판정을 받았고, 계획 대비 수행률이 ")
                    .append(ratioPct(r1)).append("%에서 ").append(ratioPct(r2))
                    .append("%로 낮아집니다. 대수를 늘리면 혼잡이 커지므로 동선 조정을 함께 검토해야 합니다.");
        } else if (r2 != null) {
            s.append(" 3D 주행 검증에서 ").append(up.amrCount()).append("대는 ")
                    .append(QuoteDocumentFactory.verdictLabel(upCheck.verdict())).append(" 판정(계획 대비 수행률 ")
                    .append(ratioPct(r2)).append("%)을 받았습니다.");
        }
        return s.toString();
    }

    // ── 12 산정 방법 ─────────────────────────────────────────────────────────

    private static List<String> method(List<Run> done, WarehouseResponse w, EstimateProperties props) {
        // 앞머리 "제목 — " 은 템플릿이 단계 제목과 본문으로 나눈다(화면에는 줄표가 나오지 않는다)
        String orders = w.outboundAvg() == null ? "같은 주문으로" : "같은 주문 " + comma(w.outboundAvg()) + "건으로";
        return List.of(
                "대수별 시뮬레이션 — " + done.get(0).amrCount() + "~" + done.get(done.size() - 1).amrCount() + "대를 " + orders
                        + " 각각 " + props.horizon().toHours() + "시간씩 운영한 결과를 비교합니다. 로봇 대수 외의 조건은 모두 같습니다.",
                "권장 대수 산정 — 목표 주문 처리율, 로봇 가동률, 예산을 모두 충족하는 대수 중 운영 효율(주문 처리율 × 로봇 가동률)이 "
                        + "가장 높은 대수를 권장합니다. 로봇을 늘려도 처리량이 거의 늘지 않기 시작하는 대수는 증설 효과 둔화 지점으로 표시합니다.",
                "3D 주행 검증 — 후보 대수마다 작업이 가장 많은 10분(피크 작업 10분)을 골라, 시뮬레이션의 이동 계획을 실제 로봇 크기와 "
                        + "속도로 3D 창고에서 주행합니다. 계획대로 제시간에 움직이는지, 로봇끼리 부딪히거나 지나치게 가까워지지 않는지 확인합니다.");
    }

    // ── 14 대수별 서비스 수준 ─────────────────────────────────────────────────

    private static List<Run> serviceRuns(EstimateDetailResponse d, List<Run> done) {
        Integer firstOver = done.stream().filter(r -> r.totalCost() != null && r.totalCost() > d.budgetLimit())
                .map(Run::amrCount).findFirst().orElse(null);
        List<Integer> picked = QuoteDocumentFactory.pickRows(done.stream().map(Run::amrCount).toList(),
                d.recommendedCount(), d.minimalCount(), d.kneeCount(), firstOver, SERVICE_ROWS);
        return done.stream().filter(r -> picked.contains(r.amrCount())).toList();
    }

    private static ServiceRow serviceRow(EstimateDetailResponse d, Run r) {
        var k = r.kpi();
        Double lead = k == null ? null : k.leadTimeMeanS();
        Double queue = k == null ? null : k.queueTimeMeanS();
        Double perHour = perHour(r);
        boolean rec = r.amrCount().equals(d.recommendedCount());
        return new ServiceRow(r.amrCount(), rec, r.amrCount().equals(d.kneeCount()) && !rec,
                pct(r.throughput()) + "%", QuoteDocumentFactory.targetMet(r, d),
                perHour == null ? "—" : Math.round(perHour) + "건",
                minutes(lead), minutes(r.leadTimeP90()),
                lead == null || queue == null || lead <= 0 ? "—" : share(queue / lead),
                pct(r.utilization()) + "%",
                k == null || k.conflictWaitRatio() == null ? "—" : ratioPct(k.conflictWaitRatio()) + "%",
                r.totalCost() == null ? "—" : won(r.totalCost()),
                r.totalCost() != null && r.totalCost() > d.budgetLimit());
    }

    private static String serviceNote(WarehouseResponse w, EstimateProperties props) {
        String orders = w.outboundAvg() == null ? "하루 주문" : "하루 주문 " + comma(w.outboundAvg()) + "건";
        return orders + "을 " + props.horizon().toHours() + "시간 동안 처리한 결과입니다. 초록색 처리율은 목표 달성, 빨간색 금액은 예산 초과를 "
                + "뜻합니다. 배정 대기 비중은 평균 주문 처리 시간 중 로봇 배정을 기다린 시간의 몫이며, 각 지표의 뜻은 13에 정리했습니다.";
    }

    // ── 15 주문이 기다리는 곳 ─────────────────────────────────────────────────

    private static List<Run> withWait(List<Run> rows) {
        return rows.stream().filter(r -> r.kpi() != null && r.kpi().leadTimeMeanS() != null
                && r.kpi().queueTimeMeanS() != null).toList();
    }

    private static WaitChart waitChart(List<Run> rows, Run rec) {
        List<Run> bars = withWait(rows);
        if (bars.isEmpty()) {
            return null;
        }
        double ih = WAIT_H - PAD_T - PAD_B, iw = W - PAD_L - PAD_R, axisY = PAD_T + ih;
        double maxMin = bars.stream().mapToDouble(r -> Math.max(r.kpi().leadTimeMeanS(),
                r.leadTimeP90() == null ? 0 : r.leadTimeP90()) / 60.0).max().orElse(1);
        double step = ceilStep(maxMin / 4, MINUTE_STEPS), top = step * 4;
        double band = iw / bars.size(), bw = Math.min(band * 0.56, 28);
        List<WaitBar> out = new ArrayList<>();
        List<AxisLabel> xLabels = new ArrayList<>();
        for (int i = 0; i < bars.size(); i++) {
            Run r = bars.get(i);
            double hQ = r.kpi().queueTimeMeanS() / 60.0 / top * ih;
            double hW = workSeconds(r) / 60.0 / top * ih;
            double yQ = axisY - hQ;
            boolean hasP90 = r.leadTimeP90() != null;
            double p90Y = hasP90 ? axisY - r.leadTimeP90() / 60.0 / top * ih : axisY;
            boolean isRec = r.amrCount().equals(rec.amrCount());
            out.add(new WaitBar(r.amrCount(), PAD_L + band * i + (band - bw) / 2, bw, yQ, hQ, yQ - GAP - hW, hW, p90Y, hasP90, isRec));
            xLabels.add(new AxisLabel(PAD_L + band * i + band / 2, r.amrCount() + "대", isRec));
        }
        List<AxisLabel> yTicks = new ArrayList<>();
        for (int j = 0; j <= 4; j++) {
            yTicks.add(new AxisLabel(axisY - j * step / top * ih, j == 0 ? "0" : oneDecimal(j * step) + "분", false));
        }
        return new WaitChart(WAIT_H, axisY, WAIT_H - PAD_B + 14, out, xLabels, yTicks);
    }

    private static String waitNote(List<Run> rows) {
        List<Run> bars = withWait(rows);
        StringBuilder s = new StringBuilder("막대 전체 높이가 평균 주문 처리 시간입니다. 아래 진한 부분은 로봇 배정을 기다린 시간, "
                + "위 연한 부분은 이동과 작업 시간이고, 가로선은 90% 기준 주문 처리 시간입니다.");
        if (bars.size() < 2) {
            return s.toString();
        }
        double minWork = bars.stream().mapToDouble(QuoteReports::workSeconds).min().orElse(0);
        double maxWork = bars.stream().mapToDouble(QuoteReports::workSeconds).max().orElse(0);
        if (maxWork > 0 && (maxWork - minWork) / maxWork < 0.25) {
            String range = minutes(minWork).equals(minutes(maxWork)) ? "약 " + minutes(maxWork)
                    : oneDecimal(minWork / 60.0) + "~" + minutes(maxWork);
            s.append(" 이동과 작업 시간은 대수와 관계없이 ").append(range).append(" 정도로 비슷합니다.");
        }
        Run first = bars.get(0), last = bars.get(bars.size() - 1);
        double firstQueue = first.kpi().queueTimeMeanS(), lastQueue = last.kpi().queueTimeMeanS();
        if (lastQueue < firstQueue * 0.9) {
            s.append(" 로봇을 ").append(first.amrCount()).append("대에서 ").append(last.amrCount()).append("대로 늘리면 배정 대기가 ")
                    .append(minutes(firstQueue)).append("에서 ").append(minutes(lastQueue)).append("까지 줄어듭니다.");
        }
        return s.toString();
    }

    private static double workSeconds(Run r) {
        return Math.max(0, r.kpi().leadTimeMeanS() - r.kpi().queueTimeMeanS());
    }

    // ── 16 한 대를 더할 때 얻는 것 ────────────────────────────────────────────

    /** 대수 → 앞 대수에서 한 대 늘릴 때마다 늘어난 시간당 처리 주문. 첫 대수와 지표가 없는 대수는 빠진다. */
    private static Map<Integer, Double> gains(List<Run> done) {
        Map<Integer, Double> out = new HashMap<>();
        for (int i = 1; i < done.size(); i++) {
            Run prev = done.get(i - 1), cur = done.get(i);
            Double a = perHour(prev), b = perHour(cur);
            if (a != null && b != null) {
                out.put(cur.amrCount(), (b - a) / (cur.amrCount() - prev.amrCount()));
            }
        }
        return out;
    }

    private static GainChart gainChart(List<Run> done, Run rec, Integer knee, Map<Integer, Double> gains) {
        List<Run> bars = done.stream().filter(r -> gains.containsKey(r.amrCount())).toList();
        if (bars.isEmpty()) {
            return null;
        }
        double ih = GAIN_H - PAD_T - PAD_B, iw = W - PAD_L - PAD_R, axisY = PAD_T + ih;
        double top = ceilStep(bars.stream().mapToDouble(r -> gains.get(r.amrCount())).max().orElse(1), GAIN_TOPS);
        double band = iw / bars.size(), bw = Math.min(band * 0.6, 24);
        List<GainBar> out = new ArrayList<>();
        List<AxisLabel> xLabels = new ArrayList<>();
        for (int i = 0; i < bars.size(); i++) {
            int n = bars.get(i).amrCount();
            double g = gains.get(n), h = Math.max(0, g) / top * ih;
            boolean isRec = n == rec.amrCount(), isKnee = Integer.valueOf(n).equals(knee) && !isRec;
            out.add(new GainBar(n, PAD_L + band * i + (band - bw) / 2, bw, axisY - h, h, isRec, isKnee,
                    isRec || isKnee ? signed(g) : null));
            xLabels.add(new AxisLabel(PAD_L + band * i + band / 2, String.valueOf(n), isRec));
        }
        List<AxisLabel> yTicks = List.of(new AxisLabel(axisY, "0", false),
                new AxisLabel(axisY - ih / 2, oneDecimal(top / 2), false), new AxisLabel(PAD_T, oneDecimal(top), false));
        return new GainChart(GAIN_H, axisY, GAIN_H - PAD_B + 14, out, xLabels, yTicks);
    }

    private static List<MarginalRow> marginalRows(List<Run> done, Run rec, Map<Integer, Double> gains) {
        int at = done.indexOf(rec);
        List<MarginalRow> out = new ArrayList<>();
        for (int i = Math.max(0, at - 1); i <= Math.min(done.size() - 1, at + 2); i++) {
            Run r = done.get(i);
            Double g = gains.get(r.amrCount());
            String lead = r.kpi() == null ? minutes(r.leadTimeP90()) : minutes(r.kpi().leadTimeMeanS()) + " / " + minutes(r.leadTimeP90());
            out.add(new MarginalRow(r.amrCount(), r == rec, r.totalCost() == null ? "—" : won(r.totalCost()),
                    pct(r.throughput()) + "%", pct(r.utilization()) + "%", lead,
                    g == null ? "—" : signed(g) + "건", costPerGain(done, i, g)));
        }
        return List.copyOf(out);
    }

    /** 늘린 로봇 한 대 값 ÷ 늘어난 시간당 처리 주문 — 시간당 1건을 늘리는 데 드는 돈. */
    private static String costPerGain(List<Run> done, int i, Double gain) {
        if (i <= 0 || gain == null || gain <= MIN_GAIN) {
            return "—";
        }
        Run prev = done.get(i - 1), cur = done.get(i);
        if (prev.totalCost() == null || cur.totalCost() == null) {
            return "—";
        }
        double perRobot = (cur.totalCost() - prev.totalCost()) / (double) (cur.amrCount() - prev.amrCount());
        return won(Math.round(perRobot / gain));
    }

    private static String marginalNote(List<Run> done, Run rec, Integer knee, Map<Integer, Double> gains) {
        int at = done.indexOf(rec);
        Double gain = gains.get(rec.amrCount());
        String here = costPerGain(done, at, gain);
        StringBuilder s = new StringBuilder();
        boolean priced = !"—".equals(here);
        if (priced) {
            s.append(rec.amrCount()).append("번째 로봇은 시간당 처리 주문 1건을 늘리는 데 ").append(here);
            Run up = at + 1 < done.size() ? done.get(at + 1) : null;
            String there = up == null ? null : costPerGain(done, at + 1, gains.get(up.amrCount()));
            if (up == null) {
                s.append("이 듭니다.");
            } else if ("—".equals(there)) {
                s.append("이 들지만, ").append(up.amrCount()).append("번째 로봇을 더해도 처리량은 거의 늘지 않습니다.");
            } else {
                s.append("이 들고, ").append(up.amrCount()).append("번째 로봇은 ").append(there).append("이 듭니다.");
            }
        } else if (gain != null) {
            s.append(rec.amrCount()).append("번째 로봇을 더해도 처리량은 거의 늘지 않습니다.");
        }
        if (knee != null && !knee.equals(rec.amrCount())) {
            s.append(s.isEmpty() ? "" : " ").append(knee).append("대부터는 비용을 더 들여도 처리량이 거의 늘지 않습니다.");
        }
        if (s.isEmpty()) {
            return "한 대를 더할 때의 효과는 표를 참고해 주세요.";
        }
        return priced ? s.append(" 비용은 로봇 한 대의 구입비와 설치비를 기준으로 계산했습니다.").toString() : s.toString();
    }

    // ── 17 피크 작업 10분 3D 주행 검증 ────────────────────────────────────────

    /** 권장 대수에 가까운 대수부터 {@link #PEAK_ROWS} 개 — 표는 대수 순으로 다시 늘어놓는다. */
    private static List<VerificationRun> peakRuns(EstimateDetailResponse d) {
        int rec = d.recommendedCount() == null ? 0 : d.recommendedCount();
        return d.verifications().stream()
                .sorted(Comparator.comparingInt((VerificationRun v) -> Math.abs(v.nRobots() - rec))
                        .thenComparingInt(VerificationRun::nRobots))
                .limit(PEAK_ROWS)
                .sorted(Comparator.comparingInt(VerificationRun::nRobots))
                .toList();
    }

    private static PeakRow peakRow(VerificationRun v, Integer recommended, LocalTime outboundStart) {
        PhysicsMetrics p = v.physics();
        Double ratio = ratio(v);
        var lag = p == null ? null : p.lag();
        return new PeakRow(v.nRobots(), v.nRobots().equals(recommended), QuoteDocumentFactory.verdictLabel(v.verdict()),
                clock(outboundStart, v.slice()),
                ratio == null ? "—" : ratioPct(ratio) + "%",
                lag == null ? "—" : QuoteFormat.seconds(lag.p50S()),
                lag == null ? "—" : QuoteFormat.seconds(lag.p90S()),
                p == null ? "—" : comma(QuoteDocumentFactory.contactCount(p)) + "회",
                p == null ? "—" : QuoteFormat.meters(p.robotMinGapM()));
    }

    /** 출고 시작 + 구간 시작 초 → "15:47–15:57". 구간을 모르면 "—". */
    static String clock(LocalTime outboundStart, VerificationRun.Slice slice) {
        if (outboundStart == null || slice == null || slice.t0S() == null) {
            return "—";
        }
        LocalTime from = outboundStart.plusSeconds((long) Math.floor(slice.t0S()));
        LocalTime to = from.plusSeconds(Math.round(slice.windowS() == null ? 600 : slice.windowS()));
        return from.format(HH_MM) + "–" + to.format(HH_MM);
    }

    private static String peakNote(boolean truncated) {
        String pass = Math.round(PhysicsVerdict.PASS_RATIO * 100) + "%";
        String more = truncated ? " 표에는 권장 대수에 가까운 " + PEAK_ROWS + "개 대수만 실었으며, 나머지는 견적 결과 화면에서 확인할 수 있습니다." : "";
        return "대수마다 작업이 가장 많은 10분을 골라 주행했기 때문에 검증 구간이 대수마다 다릅니다. 판정 기준은 적합(충돌 없음, 계획 대비 수행률 "
                + pass + " 이상), 주의(충돌 없음, " + pass + " 미만), 부적합(충돌 발생), 판정 불가(검증을 끝내지 못했거나 판정할 지표가 없음)입니다. "
                + "작업 지연은 계획보다 늦게 시작한 작업이 얼마나 늦었는지를 보통 수준과 상위 10%로 나타낸 값입니다." + more;
    }

    // ── 18 위험과 가정 ───────────────────────────────────────────────────────

    private static List<String> risks(Run rec, Run up, Map<Integer, VerificationRun> checks) {
        List<String> out = new ArrayList<>();
        int n = rec.amrCount();
        if (rec.utilization() != null && rec.utilization() >= SATURATED_UTILIZATION) {
            out.add("권장 " + n + "대의 로봇 가동률이 " + pct(rec.utilization()) + "%로 여유가 거의 없습니다. 로봇 한 대가 멈추거나 주문이 늘면 "
                    + "주문 처리율이 목표 아래로 떨어질 수 있습니다.");
        }
        VerificationRun check = checks.get(n);
        Double r1 = ratio(check);
        if (r1 != null && r1 < RATIO_RISK) {
            out.add("3D 주행 검증에서 권장 " + n + "대는 피크 작업 10분 동안 계획한 이동과 작업의 " + ratioPct(r1) + "%만 제시간에 시작했습니다. "
                    + "작업이 몰리는 시간대에는 실제 처리량이 시뮬레이션보다 낮을 수 있습니다.");
        }
        if (check != null && check.physics() != null && QuoteDocumentFactory.contactCount(check.physics()) > 0) {
            out.add("3D 주행 검증에서 권장 " + n + "대는 충돌이 " + QuoteDocumentFactory.contactCount(check.physics())
                    + "회 있었습니다. 동선과 대기 위치를 점검해야 합니다.");
        }
        Double r2 = up == null ? null : ratio(checks.get(up.amrCount()));
        if (r1 != null && r2 != null && r2 < r1) {
            out.add("3D 주행 검증에서 " + up.amrCount() + "대의 계획 대비 수행률이 " + n + "대보다 낮습니다(" + ratioPct(r1) + "% → "
                    + ratioPct(r2) + "%). 대수를 늘리면 혼잡이 커지므로 증설할 때는 동선 조정을 함께 검토해야 합니다.");
        }
        Double lead = rec.kpi() == null ? null : rec.kpi().leadTimeMeanS();
        Double queue = rec.kpi() == null ? null : rec.kpi().queueTimeMeanS();
        if (lead != null && queue != null && lead > 0 && queue / lead >= QUEUE_RISK) {
            out.add("주문 처리 시간의 " + share(queue / lead) + "가 로봇 배정 대기입니다. 주문이 한꺼번에 더 몰리면 처리 시간이 빠르게 늘어납니다.");
        }
        return out.isEmpty() ? List.of("특별히 확인된 운영 위험은 없습니다.") : List.copyOf(out);
    }

    private static List<String> assumptions(WarehouseResponse w, EstimateProperties props) {
        String window = w.outboundStart() == null || w.outboundEnd() == null ? ""
                : "출고 시간대 " + QuoteFormat.time(w.outboundStart()) + "–" + QuoteFormat.time(w.outboundEnd()) + "의 ";
        String orders = w.outboundAvg() == null ? "하루 주문을" : "하루 주문 " + comma(w.outboundAvg()) + "건을";
        return List.of(
                window + orders + " 일반적인 시간대별 분포로 나누고, " + props.horizon().toHours() + "시간 동안 처리하는 것으로 계산했습니다.",
                "주문 패턴 한 가지로만 계산했습니다. 주문이 몰리는 시각과 양이 달라지면 결과도 달라집니다.",
                "3D 주행 검증은 대수별로 가장 바쁜 10분만 주행한 결과이며, 하루 전체를 주행한 것은 아닙니다.",
                "배터리 충전 시간은 계산에 넣지 않았습니다.",
                "상자를 싣고 내리는 시간은 상자마다 같다고 보았습니다.");
    }

    // ── 공통 ────────────────────────────────────────────────────────────────

    private static Double perHour(Run r) {
        return r.kpi() == null ? null : r.kpi().throughputOrdersPerH();
    }

    private static Double ratio(VerificationRun v) {
        if (v == null || v.physics() == null || v.physics().windowActions() == null) {
            return null;
        }
        return v.physics().windowActions().ratio();
    }

    private static String contactsText(PhysicsMetrics p) {
        long c = p == null ? 0 : QuoteDocumentFactory.contactCount(p);
        return c == 0 ? "충돌은 없었습니다" : "충돌이 " + c + "회 있었습니다";
    }

    private static long cost(Run r) {
        return r.totalCost() == null ? 0 : r.totalCost();
    }

    private static Run find(List<Run> done, int count) {
        return done.stream().filter(r -> r.amrCount() == count).findFirst().orElse(null);
    }

    private static Run previous(List<Run> done, Run r) {
        int i = done.indexOf(r);
        return i <= 0 ? null : done.get(i - 1);
    }

    private static Run next(List<Run> done, Run r) {
        int i = done.indexOf(r);
        return i < 0 || i + 1 >= done.size() ? null : done.get(i + 1);
    }

    private static double round1(double v) {
        return Math.round(v * 10) / 10.0;
    }

    /** 부호는 반올림한 뒤에 정한다 — 그래야 −0.03 이 "−0" 으로 찍히지 않는다. */
    private static String signed(double v) {
        double r = round1(v);
        return r == 0 ? "0" : (r < 0 ? "−" : "+") + oneDecimal(Math.abs(r));
    }

    private static String share(double ratio) {
        return Math.round(ratio * 100) + "%";
    }

    private static double ceilStep(double value, double[] steps) {
        for (double s : steps) {
            if (s >= value) {
                return s;
            }
        }
        return steps[steps.length - 1];
    }

    private static void addIfPresent(List<String> out, String line) {
        if (line != null) {
            out.add(line);
        }
    }
}
