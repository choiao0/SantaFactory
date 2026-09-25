package com.ssafy.santafactory.service.estimate.quote;

import java.util.List;

/**
 * 견적서 템플릿에 넘기는 값 (S15P21A106-236). 숫자는 전부 표기용 문자열로 미리 만들어 템플릿은 배치만 맡는다.
 * 블록 번호·명칭은 {@code 5_Docs/Web/견적서_구성안.md} 를 따른다.
 *
 * @param verdict      권장이 없는 견적이면 {@code recommended=false} 이고 03~05·08 블록은 비운다
 * @param verification 물리 검증 전이면 null
 * @param ops          권장 run 의 상세 지표가 없으면 null
 */
public record QuoteDocument(
        String docNo,
        String issuedAt,
        String fileName,
        Issue issue,
        Verdict verdict,
        List<TargetRow> targets,
        Cost cost,
        Verification verification,
        List<FleetRow> fleet,
        String fleetNote,
        Curve curve,
        Ops ops,
        String siteUrl,
        String logoDataUri,
        /** 대수별 물리 검증 (S15P21A106-244). 한 번도 검증하지 않았으면 빈 리스트. */
        List<PhysicsRow> physicsRows,
        /** "물리 상한: N대" 한 줄. 후보 중 PASS 가 없으면 null. */
        String physicsLimitLine
) {

    /** 01 발행 정보. */
    public record Issue(String statusLine, String elapsed, String model,
                        String warehouseName, String sizeLine, String workers, String windowLine,
                        String dailyOrders, String ordersNote) {
    }

    /** 02 권장 구성. */
    public record Verdict(boolean recommended, String model, Integer count, String okLine, String lead, String reasonText,
                          String throughput, String throughputNote, String utilization, String utilizationNote,
                          String costEok, String costNote, String leadTimeMin, String leadTimeNote) {
    }

    /** 03 목표 달성 여부의 한 행. {@code ok} 가 null 이면 판정 밖(참고). */
    public record TargetRow(String label, String target, String actual, Boolean ok, String verdict, String note) {
    }

    /** 04 예상 구축 비용. */
    public record Cost(String unitPrice, String installPerUnit, String countText, String unitAmount, String installAmount,
                       String extraLabel, String extraAmount, String total, String budgetText,
                       double usedPct, String usedPctText, String remaining) {
    }

    /** 05 권장 구성 물리 검증 결과. */
    public record Verification(String methodLine, String windowLine, boolean resultOk, String resultLine,
                               boolean hasComparison, List<CompareRow> rows, String noticeText) {
    }

    public record CompareRow(String label, String expected, String verified, String diff, boolean warn) {
    }

    /** 05 부록 — 대수 하나의 물리 검증 판정 한 행 (S15P21A106-244). */
    public record PhysicsRow(int count, boolean recommended, String verdictLabel,
                             String windowRatio, String lagP50, String contacts, String minGap) {
    }

    /** 06 로봇 대수별 비교의 한 행. */
    public record FleetRow(int count, boolean recommended, boolean minimal, boolean full, boolean knee,
                           String throughput, String utilization, boolean targetOk, String targetText,
                           String efficiency, String dailyOrders, String cost, boolean overBudget) {
    }

    /** 07 효율·구축 비용 그래프 — SVG 좌표는 템플릿 viewBox(672 × 175) 기준. */
    public record Curve(String effPath, String thrPath, String costPath, List<Point> points,
                        double svgH, double axisY, double xLabelY,
                        List<AxisLabel> xLabels, List<AxisLabel> xLabelsThr, List<AxisLabel> yLeft,
                        List<AxisLabel> yRight, double budgetY, String budgetLabel,
                        double recX, double recY, String recLabel,
                        Mark minimal, Mark minimalThr, Mark thrPeak) {
    }

    /**
     * 대수 하나의 점. {@code met} 은 목표(처리율·가동률·예산)를 다 넘었나 — 못 넘은 대수는 회색 빈 점으로
     * 그려 06 표의 미달 행과 같은 말을 하게 한다.
     */
    public record Point(double x, double effY, double thrY, boolean met) {
    }

    /** 곡선 위의 표식 하나 — 자리와 이름. 이름은 그림이 아니라 범례에 적는다. 없으면 null. */
    public record Mark(double x, double y, String label) {
    }

    public record AxisLabel(double pos, String text, boolean highlight) {
    }

    /** 08 권장 구성의 운영 예상. */
    public record Ops(String leadMeanMin, String queueMin, String conflictPct, String distanceKm, String robotsLine) {
    }
}
