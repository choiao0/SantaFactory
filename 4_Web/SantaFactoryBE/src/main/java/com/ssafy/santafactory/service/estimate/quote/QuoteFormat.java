package com.ssafy.santafactory.service.estimate.quote;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.text.NumberFormat;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.Locale;

/** 견적서 표기 규칙 — 웹 화면 {@code utils/format.js} 와 같은 결과가 나오게 맞춘다 (S15P21A106-236). */
final class QuoteFormat {

    private static final DateTimeFormatter DATE_TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm");
    private static final DateTimeFormatter DOC_DATE = DateTimeFormatter.ofPattern("yyyyMMdd");
    private static final DateTimeFormatter HH_MM = DateTimeFormatter.ofPattern("HH:mm");
    private static final long EOK = 100_000_000L;
    private static final long MAN = 10_000L;

    private QuoteFormat() {
    }

    /** {@code EST-20260917-0142}. */
    static String docNo(LocalDateTime createdAt, long id) {
        return "EST-%s-%04d".formatted(createdAt.format(DOC_DATE), id);
    }

    static String dateTime(LocalDateTime value) {
        return value == null ? "—" : value.format(DATE_TIME);
    }

    static String time(LocalTime value) {
        return value == null ? "—" : value.format(HH_MM);
    }

    /** 원 → "2억 1,700만 원" / "1,550만 원" / "9,000원". 화면 {@code formatWon} 과 같은 만원 반올림. */
    static String won(long value) {
        if (value < MAN) {
            return comma(value) + "원";
        }
        long man = Math.round(value / (double) MAN);
        long eok = man / MAN;
        long rest = man % MAN;
        if (eok == 0) {
            return comma(rest) + "만 원";
        }
        return rest == 0 ? eok + "억 원" : eok + "억 " + comma(rest) + "만 원";
    }

    /** 원 → "2.17" (억 단위, 소수 둘째 자리까지, 끝 0 제거). */
    static String eok(long value) {
        return BigDecimal.valueOf(value).divide(BigDecimal.valueOf(EOK), 2, RoundingMode.HALF_UP)
                .stripTrailingZeros().toPlainString();
    }

    static String comma(long value) {
        return NumberFormat.getIntegerInstance(Locale.KOREA).format(value);
    }

    /** 초 → "6.4분". */
    static String minutes(Double seconds) {
        return seconds == null ? "—" : oneDecimal(seconds / 60.0) + "분";
    }

    /** 초 → "48초" (반올림). */
    static String seconds(Double seconds) {
        return seconds == null ? "—" : Math.round(seconds) + "초";
    }

    /** 0~1 비율 → "6.8". */
    static String ratioPct(Double ratio) {
        return ratio == null ? "—" : oneDecimal(ratio * 100.0);
    }

    /** % 값 → "95.6" (정수면 소수 없이). 화면 {@code formatPercent} 와 같다. */
    static String pct(Double percent) {
        return percent == null ? "—" : oneDecimal(percent);
    }

    /** m → "171" km (반올림). */
    static String km(Long meters) {
        return meters == null ? "—" : String.valueOf(Math.round(meters / 1000.0));
    }

    static String oneDecimal(double value) {
        if (value == Math.rint(value)) {
            return String.valueOf((long) value);
        }
        return BigDecimal.valueOf(value).setScale(1, RoundingMode.HALF_UP).stripTrailingZeros().toPlainString();
    }

    /** 초 → "18분 42초" / "42초" / "1시간 3분". */
    static String elapsed(Long totalSeconds) {
        if (totalSeconds == null) {
            return "—";
        }
        Duration d = Duration.ofSeconds(totalSeconds);
        if (d.toHours() > 0) {
            return d.toHours() + "시간 " + d.toMinutesPart() + "분";
        }
        if (d.toMinutes() > 0) {
            return d.toMinutes() + "분 " + d.toSecondsPart() + "초";
        }
        return d.toSeconds() + "초";
    }

    /** 부호 붙은 퍼센트 변화 "+8 %" / "−4 %". */
    static String signedPct(double ratio) {
        long v = Math.round(ratio * 100.0);
        return (v < 0 ? "−" : "+") + Math.abs(v) + " %";
    }

    /** 부호 붙은 퍼센트포인트 변화 "+1.3 %p". */
    static String signedPoints(double ratioDiff) {
        double v = ratioDiff * 100.0;
        return (v < 0 ? "−" : "+") + oneDecimal(Math.abs(v)) + " %p";
    }
}
