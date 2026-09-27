package com.ssafy.santafactory.service.estimate.quote;

import com.ssafy.santafactory.service.estimate.quote.QuoteDocument.AxisLabel;

import java.util.List;

/**
 * 견적서 3~5쪽 「도입 검토 보고서」 (S15P21A106-280). 권장 대수가 있는 견적만 싣는다. {@link QuoteDocument} 처럼
 * 숫자는 표기용 문자열·SVG 좌표로 미리 만들어 템플릿은 배치만 맡는다. 그래프 좌표는 viewBox 가로 672 기준.
 *
 * @param alternativeTitle 권장보다 큰 대수를 돌리지 않았으면 null (이때 {@code alternative} 도 null)
 * @param waitChart        상세 지표(주문 처리 시간·배정 대기)가 있는 대수가 없으면 null
 * @param marginal         시간당 처리량이 있는 대수가 둘 미만이면 null
 * @param peak             3D 주행 검증을 한 번도 안 했으면 빈 리스트
 */
public record QuoteReport(
        List<String> basis,
        String alternativeTitle,
        String alternative,
        List<String> method,
        List<ServiceRow> service,
        String serviceNote,
        WaitChart waitChart,
        String waitNote,
        GainChart marginal,
        List<MarginalRow> marginalRows,
        String marginalNote,
        List<PeakRow> peak,
        String peakNote,
        List<String> risks,
        List<String> assumptions
) {

    /** 14 대수별 서비스 수준 한 행. */
    public record ServiceRow(int count, boolean recommended, boolean knee, String throughput, boolean targetOk,
                             String perHour, String leadMean, String leadP90, String queueShare, String utilization,
                             String conflict, String cost, boolean overBudget) {
    }

    /** 15 누적 막대 하나 — 아래 로봇 배정 대기, 위 이동·작업, 가로선 상위 10% 주문 처리 시간. */
    public record WaitBar(int count, double x, double w, double yQueue, double hQueue, double yWork, double hWork,
                          double p90Y, boolean hasP90, boolean recommended) {
    }

    public record WaitChart(double svgH, double axisY, double xLabelY, List<WaitBar> bars,
                            List<AxisLabel> xLabels, List<AxisLabel> yTicks) {
    }

    /** 16 한 대 더할 때 늘어나는 시간당 처리량 막대. {@code label} 은 권장·증설 효과 둔화 지점에만 붙인다. */
    public record GainBar(int count, double x, double w, double y, double h, boolean recommended, boolean knee,
                          String label) {
    }

    public record GainChart(double svgH, double axisY, double xLabelY, List<GainBar> bars,
                            List<AxisLabel> xLabels, List<AxisLabel> yTicks) {
    }

    /** 16 권장 앞뒤 대수의 비용 대비 효과 한 행. */
    public record MarginalRow(int count, boolean recommended, String cost, String throughput, String utilization,
                              String lead, String gain, String costPerGain) {
    }

    /** 17 대수 하나의 피크 작업 10분 3D 주행 결과. {@code window} 는 실제 시각("15:47–15:57"). */
    public record PeakRow(int count, boolean recommended, String verdict, String window, String ratio,
                          String lagP50, String lagP90, String contacts, String minGap) {
    }
}
