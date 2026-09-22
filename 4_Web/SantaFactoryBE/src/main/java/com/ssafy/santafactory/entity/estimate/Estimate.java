package com.ssafy.santafactory.entity.estimate;

import com.ssafy.santafactory.entity.warehouse.Warehouse;
import jakarta.persistence.Column;
import jakarta.persistence.Embedded;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 견적 1건 — 요청 시점의 목표·예산과 스윕 전체의 결론.
 *
 * <p>대수별 결과는 {@code SimScenarios} 에 1행씩 쌓이고, 이 테이블은 "그래서 몇 대가 답인가"를 담는다.
 * 목표 3개를 {@code Warehouses} 에서 복사해 두는 이유는 창고 설정이 나중에 바뀌어도 과거 견적의
 * 판정 근거가 소급 변경되지 않게 하기 위함이다(창고 행은 1개뿐이라 견적마다 다른 예산을 담을 수도 없다).
 *
 * <p>단위는 % — {@code Warehouses.target_throughput}·{@code target_utilization} 규약을 따른다.
 */
@Entity
@Table(name = "Estimates")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Estimate {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "estimate_id")
    private Long id;

    /** 운영조건·레이아웃 출처. 시뮬 요청 메시지를 만들 때 이 창고의 값을 읽는다. */
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "warehouse_id", nullable = false)
    private Warehouse warehouse;

    @Column(name = "amr_model", nullable = false, length = 100)
    private String amrModel;

    /** 목표 출고 처리율 %. 생성 시 창고 값 복사. */
    @Column(name = "target_throughput", nullable = false)
    private Double targetThroughput;

    /** 목표 AMR 가동률 %. 생성 시 창고 값 복사. */
    @Column(name = "target_utilization", nullable = false)
    private Double targetUtilization;

    /** 목표 구축 비용(원). 생성 시 창고 값 복사. */
    @Column(name = "budget_limit", nullable = false)
    private Long budgetLimit;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private EstimateStatus status;

    /** 3조건을 모두 만족하는 최소 대수. 없으면 null 이고 이때만 reasonCode 가 채워진다. */
    @Column(name = "recommended_count")
    private Integer recommendedCount;

    /** 대수를 늘려도 처리율이 거의 오르지 않기 시작하는 대수. 판정 불가면 null. */
    @Column(name = "knee_count")
    private Integer kneeCount;

    /**
     * 목표를 모두 만족하는 대수 중 가장 적은 대수 — 권장과 같은 조건을 통과하되 효율이 아니라 비용을 본다.
     * 권장과 같은 값일 수도 있고, 그때는 화면이 두 표시를 하나로 합친다. 판정 불가면 null.
     */
    @Column(name = "minimal_count")
    private Integer minimalCount;

    @Enumerated(EnumType.STRING)
    @Column(name = "reason_code", length = 30)
    private ReasonCode reasonCode;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

    /** 마지막 run 결과가 도착한 시각. createdAt 과의 차이가 견적 소요시간(90초 목표 측정). */
    @Column(name = "completed_at")
    private LocalDateTime completedAt;

    /** 물리 검증(Isaac) 리플레이 영상 URL. 검증 전이거나 실패해 영상이 없으면 null. */
    @Column(name = "verify_video_url", length = 500)
    private String verifyVideoUrl;

    /**
     * 물리 검증을 큐에 발행한 시각. 결과가 오기 전까지 "요청했다" 를 알 수 있는 유일한 흔적이라,
     * 중복 발행을 막는 데 쓴다. 검증한 적이 없으면 null.
     */
    @Column(name = "verify_requested_at")
    private LocalDateTime verifyRequestedAt;

    /** 같은 검증의 측면 시점 영상. 측면을 찍지 않은 회차는 null 이고 화면은 상단만 보여준다. */
    @Column(name = "verify_video_side_url", length = 500)
    private String verifyVideoSideUrl;

    /**
     * 이 견적의 대수 스윕 전체가 공유하는 출고 주문 목록(JSON 직렬화, {@code SimulationRequest.Outbound[]}).
     * 대수마다 다시 생성하지 않고 여기 저장된 걸 재사용한다 — 그래야 "같은 주문량을 몇 대가 처리하는가"를
     * 대수별로 비교하는 게 의미 있다.
     */
    @Column(name = "outbound_orders_json")
    private String outboundOrdersJson;

    /**
     * 리플레이 맵 — 격자·장애물·존·스테이션 (S15P21A106-205). run 마다 함께 오지만 대수와 무관하게
     * 같은 값이라 견적당 한 벌만 둔다. run 쪽에 두면 143 KB 짜리가 대수만큼(최대 28번) 중복된다.
     */
    @Column(name = "replay_scene_json")
    private String replaySceneJson;

    /** 물리 검증 결과 (S15P21A106-236). 검증 전이면 null. 재검증하면 덮어쓴다. */
    @Embedded
    private VerifySnapshot verify;

    private Estimate(Warehouse warehouse, String amrModel,
                     double targetThroughput, double targetUtilization, long budgetLimit) {
        this.warehouse = warehouse;
        this.amrModel = amrModel;
        this.targetThroughput = targetThroughput;
        this.targetUtilization = targetUtilization;
        this.budgetLimit = budgetLimit;
        this.status = EstimateStatus.RUNNING;
    }

    /**
     * 견적을 열어 RUNNING 으로 시작한다. 목표·예산은 호출자가 창고 값 또는 요청 값으로 넘긴다.
     *
     * @param targetThroughput  목표 출고 처리율 %
     * @param targetUtilization 목표 AMR 가동률 %
     * @param budgetLimit       목표 구축 비용, 원
     */
    public static Estimate open(Warehouse warehouse, String amrModel,
                                double targetThroughput, double targetUtilization, long budgetLimit) {
        return new Estimate(warehouse, amrModel, targetThroughput, targetUtilization, budgetLimit);
    }

    /**
     * 전 대수 완료 후 판정 결과를 확정한다.
     *
     * <p>권장 대수·무릎·사유를 한 번에 넣어 "권장 대수가 있으면 사유는 없다"는 배타 관계를 유지하고,
     * 완료 시각도 같이 찍어 빠뜨릴 수 없게 한다. 취소된 견적은 뒤늦게 결과가 와도 되살리지 않는다
     * (같은 run_id 가 두 번 올 수 있다 — 명세 §1-3).
     *
     * @param anyFailed 실패·타임아웃 run 이 하나라도 있었나 (있으면 PARTIAL)
     */
    public void complete(Integer recommendedCount, Integer minimalCount, Integer kneeCount,
                         ReasonCode reasonCode, boolean anyFailed) {
        if (status == EstimateStatus.CANCELLED) {
            return;
        }
        this.recommendedCount = recommendedCount;
        this.minimalCount = minimalCount;
        this.kneeCount = kneeCount;
        this.reasonCode = reasonCode;
        this.status = anyFailed ? EstimateStatus.PARTIAL : EstimateStatus.DONE;
        this.completedAt = LocalDateTime.now();
    }

    /** 사용자 취소. 이미 끝난 견적은 건드리지 않는다. */
    public void cancel() {
        if (status == EstimateStatus.RUNNING) {
            this.status = EstimateStatus.CANCELLED;
        }
    }

    public boolean isCancelled() {
        return status == EstimateStatus.CANCELLED;
    }

    /** 물리 검증을 큐에 발행했다고 표시한다. 재요청이면 시각을 새로 덮는다. */
    public void markVerifyRequested(LocalDateTime at) {
        this.verifyRequestedAt = at;
    }

    /** 물리 검증 결과로 받은 시점별 영상 URL을 반영한다. 측면은 없을 수 있다. */
    public void applyVerifyVideo(String url, String sideUrl) {
        this.verifyVideoUrl = url;
        this.verifyVideoSideUrl = sideUrl;
    }

    /** 물리 검증 결과를 반영한다. 영상과 같이 성패를 가리지 않고 마지막 결과를 남긴다. */
    public void applyVerifyResult(VerifySnapshot snapshot) {
        if (snapshot != null) {
            this.verify = snapshot;
        }
    }

    /**
     * 리플레이 맵을 붙인다. 먼저 도착한 run 것만 쓰고 이후는 버린다 — 어차피 같은 값이라
     * 매번 덮어쓰면 같은 143 KB 를 run 수만큼 다시 쓰는 UPDATE 가 된다.
     */
    public void applyReplayScene(String sceneJson) {
        if (sceneJson != null && this.replaySceneJson == null) {
            this.replaySceneJson = sceneJson;
        }
    }

    /** 대수 스윕 발행 전, 백엔드가 생성한 출고 주문 목록(JSON)을 붙인다. */
    public void applyOutboundOrders(String outboundOrdersJson) {
        this.outboundOrdersJson = outboundOrdersJson;
    }

    /** 견적 소요시간(초). 아직 완료 전이면 null — 90초 목표 측정에 쓴다. */
    public Long elapsedSeconds() {
        if (completedAt == null) {
            return null;
        }
        return java.time.Duration.between(createdAt, completedAt).toSeconds();
    }

    @PrePersist
    void onCreate() {
        this.createdAt = LocalDateTime.now();
        this.updatedAt = this.createdAt;
    }

    @PreUpdate
    void onUpdate() {
        this.updatedAt = LocalDateTime.now();
    }
}
