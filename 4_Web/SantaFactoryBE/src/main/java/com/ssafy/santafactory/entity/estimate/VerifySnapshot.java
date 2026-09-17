package com.ssafy.santafactory.entity.estimate;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 물리 검증(Isaac) 결과 한 벌 (S15P21A106-236, 계약 SIM_VERIFY_CONTRACT.md §3).
 * 비교에 쓰는 지표 3개만 담는다 — 검증은 피크 10분 창이라 처리율 % 는 계산과 비교할 수 없다.
 * {@code warningsJson} 이 null 이면 계산과 같은 조건에서 돈 것이다.
 */
@Embeddable
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class VerifySnapshot {

    static final String NORMAL_END = "window elapsed";
    static final String DONE = "done";

    @Column(name = "verify_run_id", length = 64)
    private String runId;

    @Column(name = "verify_status", length = 20)
    private String status;

    @Column(name = "verify_reason", length = 100)
    private String reason;

    @Column(name = "verify_error", length = 500)
    private String error;

    @Column(name = "verify_n_robots")
    private Integer nRobots;

    @Column(name = "verify_robots_online")
    private Integer robotsOnline;

    @Column(name = "verify_window_s")
    private Integer windowS;

    @Column(name = "verify_warnings_json")
    private String warningsJson;

    @Column(name = "verify_throughput_orders_per_h")
    private Double throughputOrdersPerH;

    @Column(name = "verify_lead_time_p90_s")
    private Double leadTimeP90S;

    @Column(name = "verify_conflict_wait_ratio")
    private Double conflictWaitRatio;

    @Column(name = "verified_at")
    private LocalDateTime verifiedAt;

    public VerifySnapshot(String runId, String status, String reason, String error,
                          Integer nRobots, Integer robotsOnline, Integer windowS, String warningsJson,
                          Double throughputOrdersPerH, Double leadTimeP90S, Double conflictWaitRatio,
                          LocalDateTime verifiedAt) {
        this.runId = runId;
        this.status = status;
        this.reason = truncate(reason, 100);
        this.error = truncate(error, 500);
        this.nRobots = nRobots;
        this.robotsOnline = robotsOnline;
        this.windowS = windowS;
        this.warningsJson = warningsJson;
        this.throughputOrdersPerH = throughputOrdersPerH;
        this.leadTimeP90S = leadTimeP90S;
        this.conflictWaitRatio = conflictWaitRatio;
        this.verifiedAt = verifiedAt;
    }

    /** 창이 끝까지 돌고 done 으로 끝났는가. reason 이 없는 옛 페이로드는 status 만 본다. */
    public boolean finishedNormally() {
        return DONE.equals(status) && (reason == null || NORMAL_END.equals(reason));
    }

    public boolean ranUnderDifferentConditions() {
        return warningsJson != null;
    }

    public boolean fleetPartiallyOnline() {
        return nRobots != null && robotsOnline != null && robotsOnline < nRobots;
    }

    public boolean hasKpi() {
        return throughputOrdersPerH != null || leadTimeP90S != null || conflictWaitRatio != null;
    }

    private static String truncate(String value, int max) {
        return value == null || value.length() <= max ? value : value.substring(0, max);
    }
}
