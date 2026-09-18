package com.ssafy.santafactory.entity.simulation;

import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.entity.estimate.RunStatus;
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
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 대수 하나에 대한 시뮬 실행 1건 — 견적의 하위 단위(run).
 *
 * <p>{@code round}(창고 참조)를 {@code estimate_id}(견적 참조)로 바꿨다. 창고는 견적을 거쳐 도달한다 —
 * 경로가 둘이면 run 의 창고와 그 run 이 속한 견적의 창고가 어긋날 수 있다.
 *
 * <p>KPI 4개({@code utilization}·{@code outbound}·{@code throughput}·{@code total_cost})는 기존 컬럼을
 * 그대로 쓴다. 나머지 KPI(리드타임·makespan 등)는 run 상세 조회 API 를 만들 때 추가한다.
 */
@Entity
// 실제 테이블명은 simscenarios 다. "SimScenarios" 로 두면 Hibernate 기본 네이밍 전략이
// sim_scenarios 로 바꿔 버려서 ddl-auto=update 일 때 테이블이 하나 더 생긴다.
@Table(name = "simscenarios")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class SimScenario {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "scenario_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "estimate_id", nullable = false)
    private Estimate estimate;

    /** 시뮬 큐 식별자 {@code est_77_n3}. 유니크 — 같은 결과가 두 번 와도 이걸로 걸러낸다. */
    @Column(name = "run_id", nullable = false, unique = true, length = 64)
    private String runId;

    @Column(name = "amr_count", nullable = false)
    private Integer amrCount;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private RunStatus status;

    /** status=FAILED 일 때만. */
    @Column(name = "error", length = 500)
    private String error;

    /** 큐 발행 시각. TIMEOUT 판정과 견적 소요시간 측정에 쓴다. */
    @Column(name = "published_at", nullable = false)
    private LocalDateTime publishedAt;

    @Column(name = "completed_at")
    private LocalDateTime completedAt;

    /** AMR 가동률 %. */
    @Column(name = "utilization")
    private Double utilization;

    /** 출고 처리 건수(건/일). */
    @Column(name = "outbound")
    private Long outbound;

    /** 출고 처리율 %. */
    @Column(name = "throughput")
    private Double throughput;

    /** 총 구축 비용(원). 대수만으로 정해지므로 발행 시점에 채운다. */
    @Column(name = "total_cost")
    private Long totalCost;

    /**
     * 주문 리드타임 p90(초) — 명세 §1-2 {@code kpi.lead_time_p90_s} (S15P21A106-97).
     * 시뮬이 안 주면 null 이고, 그 run 은 리드타임 조건을 건너뛴다.
     */
    @Column(name = "lead_time_p90")
    private Double leadTimeP90;

    /**
     * 이 run 의 앞 구간 궤적 (S15P21A106-205). 시뮬이 준 JSON 을 그대로 담는다.
     * 맵({@code scene})은 대수와 무관하게 같으므로 여기가 아니라 견적 쪽에 한 벌만 둔다.
     */
    @Column(name = "replay_json")
    private String replayJson;

    /** 판정 밖 상세 지표 7개 (S15P21A106-236). 전부 NULL 이면 Hibernate 가 null 로 읽는다. */
    @Embedded
    private RunKpiDetail kpiDetail;

    private SimScenario(Estimate estimate, String runId, int amrCount, long totalCost) {
        this.estimate = estimate;
        this.runId = runId;
        this.amrCount = amrCount;
        this.totalCost = totalCost;
        this.status = RunStatus.QUEUED;
        this.publishedAt = LocalDateTime.now();
    }

    /** 큐에 발행한 run 1건. 비용은 대수만으로 정해지므로 여기서 이미 확정된다. */
    public static SimScenario queued(Estimate estimate, String runId, int amrCount, long totalCost) {
        return new SimScenario(estimate, runId, amrCount, totalCost);
    }

    /** 워커가 이 run 을 집었다 ({@code status: running} 수신). 재전달로 두 번 와도 그대로 RUNNING. */
    public void markRunning() {
        this.status = RunStatus.RUNNING;
    }

    /**
     * 결과 수신 — KPI 를 채우고 DONE 으로 넘긴다.
     *
     * @param throughput   출고 처리율 %
     * @param utilization  AMR 가동률 %
     * @param outbound     출고 처리 건수
     * @param leadTimeP90  주문 리드타임 p90(초). 시뮬이 안 주면 null
     */
    public void markDone(Double throughput, Double utilization, Long outbound, Double leadTimeP90) {
        this.throughput = throughput;
        this.utilization = utilization;
        this.outbound = outbound;
        this.leadTimeP90 = leadTimeP90;
        this.error = null;
        this.status = RunStatus.DONE;
        this.completedAt = LocalDateTime.now();
    }

    /**
     * 앞 구간 궤적을 붙인다. 없으면(내보내기를 끄거나 시뮬이 못 만들었으면) 아무것도 하지 않는다 —
     * 리플레이가 없다고 이미 받아 둔 KPI 를 지울 이유가 없다.
     */
    public void applyReplay(String replayJson) {
        if (replayJson != null) {
            this.replayJson = replayJson;
        }
    }

    /** 상세 지표를 붙인다. 없으면 그대로 둔다 — 판정에 쓰는 KPI 와 별개라 DONE 전이에 영향이 없다. */
    public void applyKpiDetail(RunKpiDetail detail) {
        if (detail != null) {
            this.kpiDetail = detail;
        }
    }

    /** 시뮬이 실패로 응답 — 사유를 남기고 나머지 run 은 계속 진행한다. */
    public void markFailed(String error) {
        this.error = truncate(error);
        this.status = RunStatus.FAILED;
        this.completedAt = LocalDateTime.now();
    }

    /** 정해진 시간 안에 결과가 오지 않음. */
    public void markTimeout() {
        this.status = RunStatus.TIMEOUT;
        this.completedAt = LocalDateTime.now();
    }

    /** 더 이상 결과를 기다리지 않는 상태. 중복 결과를 무시할 때 본다. */
    public boolean isFinished() {
        return status.isFinished();
    }

    /** 판정에 쓸 수 있는 결과인가 — DONE 이고 KPI 가 채워져 있어야 한다. */
    public boolean hasKpi() {
        return status == RunStatus.DONE && throughput != null && utilization != null;
    }

    /** error 컬럼이 500자라 시뮬 traceback 이 그대로 오면 잘라서 넣는다. */
    private String truncate(String message) {
        if (message == null) {
            return null;
        }
        return message.length() <= 500 ? message : message.substring(0, 500);
    }
}
