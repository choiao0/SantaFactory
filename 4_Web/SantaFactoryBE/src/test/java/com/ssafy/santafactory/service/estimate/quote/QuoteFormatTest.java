package com.ssafy.santafactory.service.estimate.quote;

import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;

import static org.assertj.core.api.Assertions.assertThat;

class QuoteFormatTest {

    @Test
    void won_matches_the_web_formatter() {
        assertThat(QuoteFormat.won(217_000_000L)).isEqualTo("2억 1,700만 원");
        assertThat(QuoteFormat.won(1_200_000_000L)).isEqualTo("12억 원");
        assertThat(QuoteFormat.won(15_500_000L)).isEqualTo("1,550만 원");
        assertThat(QuoteFormat.won(9_000L)).isEqualTo("9,000 원");
    }

    @Test
    void eok_keeps_two_decimals_without_trailing_zeros() {
        assertThat(QuoteFormat.eok(217_000_000L)).isEqualTo("2.17");
        assertThat(QuoteFormat.eok(300_000_000L)).isEqualTo("3");
        assertThat(QuoteFormat.eok(125_000_000L)).isEqualTo("1.25");
    }

    @Test
    void times_are_shown_in_minutes_for_orders_and_seconds_for_waits() {
        assertThat(QuoteFormat.minutes(384.0)).isEqualTo("6.4분");
        assertThat(QuoteFormat.minutes(4820.0)).isEqualTo("80.3분");
        assertThat(QuoteFormat.minutes(null)).isEqualTo("—");
        assertThat(QuoteFormat.seconds(47.6)).isEqualTo("48초");
    }

    @Test
    void percent_like_values() {
        assertThat(QuoteFormat.pct(95.6)).isEqualTo("95.6");
        assertThat(QuoteFormat.pct(100.0)).isEqualTo("100");
        assertThat(QuoteFormat.ratioPct(0.068)).isEqualTo("6.8");
        assertThat(QuoteFormat.signedPct(-0.044)).isEqualTo("−4%");
        assertThat(QuoteFormat.signedPct(0.078)).isEqualTo("+8%");
        assertThat(QuoteFormat.signedPoints(0.013)).isEqualTo("+1.3%p");
    }

    @Test
    void document_number_uses_created_date_and_zero_padded_id() {
        assertThat(QuoteFormat.docNo(LocalDateTime.of(2026, 9, 17, 14, 32), 142L)).isEqualTo("EST-20260917-0142");
        assertThat(QuoteFormat.docNo(LocalDateTime.of(2026, 1, 2, 0, 0), 12345L)).isEqualTo("EST-20260102-12345");
    }
}
