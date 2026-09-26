package com.ssafy.santafactory.entity.estimate;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 견적×대수 하나의 물리 검증(Isaac) 회차 (S15P21A106-244). 같은 (견적, 대수)를 다시 검증하면
 * {@code attempt} 를 올려 새 행을 쌓는다 — {@link com.ssafy.santafactory.entity.estimate.VerifySnapshot}
 * (견적당 한 벌)과 달리 여러 대수를 동시에, 여러 번 검증할 수 있어야 해서다.
 *
 * <p>권장 대수의 결과는 이 행과 별개로 {@code Estimate.verify} 스냅샷에도 반영된다 — 옛 화면·PDF 가
 * 그 스냅샷만 보고 동작하기 때문이다.
 */
@Entity
@Table(name = "estimate_verifications")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class EstimateVerification {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "estimate_id", nullable = false)
    private Estimate estimate;

    @Column(name = "n_robots", nullable = false)
    private Integer robotCount;          // 컬럼 n_robots. nRobots 로 두면 스프링 데이터가 …ByNRobots… 를 못 푼다(-244)

    /** 같은 (견적, 대수)의 몇 번째 요청인가 — 1부터. */
    @Column(name = "attempt", nullable = false)
    private Integer attempt;

    /** {@code verify_<estimateId>_n<nRobots>_<attempt>} — host-orch 의 멱등 키. */
    @Column(name = "run_id", nullable = false, unique = true, length = 64)
    private String runId;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 16)
    private VerifyRunStatus status;

    @Column(name = "error", length = 500)
    private String error;

    /** host-orch {@code verify.reason} — 예: "window elapsed". */
    @Column(name = "reason", length = 64)
    private String reason;

    /** 영상 객체 키(상단 시점). 1인칭은 이름 규칙으로 유도한다({@code VerifyVideoPresigner}). */
    @Column(name = "video_key")
    private String videoKey;

    /** 명세 §C {@code physics} 원본 JSON. */
    @Column(name = "physics_json")
    private String physicsJson;

    /** 명세 §3 {@code verify} 원본 JSON — 회차별 원인 추적용. */
    @Column(name = "verify_json")
    private String verifyJson;

    /** 요청 시 쓴 구간 메타(JSON, {@link com.ssafy.santafactory.dto.simulation.VerifySliceMeta}). 폴백 요청이면 null. */
    @Column(name = "slice_meta_json")
    private String sliceMetaJson;

    @Column(name = "requested_at", nullable = false)
    private LocalDateTime requestedAt;

    @Column(name = "finished_at")
    private LocalDateTime finishedAt;

    private EstimateVerification(Estimate estimate, int nRobots, int attempt, String runId, String sliceMetaJson) {
        this.estimate = estimate;
        this.robotCount = nRobots;
        this.attempt = attempt;
        this.runId = runId;
        this.sliceMetaJson = sliceMetaJson;
        this.status = VerifyRunStatus.PENDING;
        this.requestedAt = LocalDateTime.now();
    }

    /** 발행 직후 PENDING 행 1건. */
    public static EstimateVerification requested(Estimate estimate, int nRobots, int attempt, String runId,
                                                 String sliceMetaJson) {
        return new EstimateVerification(estimate, nRobots, attempt, runId, sliceMetaJson);
    }

    /** 아직 결과를 기다리는 중인가 — 중복 요청 가드에 쓴다. */
    public boolean isPending() {
        return !status.isFinished();
    }

    public void markRunning() {
        this.status = VerifyRunStatus.RUNNING;
    }

    /** 결과 반영 — 성패와 무관하게 마지막 결과로 덮는다(같은 결과가 두 번 와도 안전). */
    public void applyResult(VerifyRunStatus status, String error, String reason, String videoKey,
                            String physicsJson, String verifyJson) {
        this.status = status;
        this.error = error;
        this.reason = reason;
        if (videoKey != null) {
            this.videoKey = videoKey;
        }
        this.physicsJson = physicsJson;
        this.verifyJson = verifyJson;
        if (status.isFinished()) {
            this.finishedAt = LocalDateTime.now();
        }
    }
}
