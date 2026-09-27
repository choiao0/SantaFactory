package com.ssafy.santafactory.entity.simulation;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * run 하나의 DES 피크 구간(물리 검증용) — {@link RunReplay} 와 같은 자리(scenario_id 1:1)를 쓰지만
 * 별도 테이블이다 (S15P21A106-244). 구간을 못 만든 run 도 사유를 보여야 해서 {@code gzB64} 는 null 이어도
 * 행은 만든다 — {@link #hasTrajectory()} 로 구분한다.
 */
@Entity
@Table(name = "simscenario_verify_slices")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class SimScenarioVerifySlice {

    @Id
    @Column(name = "scenario_id")
    private Long scenarioId;

    /** {@code verify_slice} 에서 {@code gz_b64} 를 뺀 나머지 — JSON({@link com.ssafy.santafactory.dto.simulation.VerifySliceMeta}). */
    @Column(name = "meta_json", nullable = false)
    private String metaJson;

    /** gzip+base64 궤적. 구간을 못 만들었으면(상한 초과 등) null. */
    @Column(name = "gz_b64")
    private String gzB64;

    public SimScenarioVerifySlice(Long scenarioId, String metaJson, String gzB64) {
        this.scenarioId = scenarioId;
        this.metaJson = metaJson;
        this.gzB64 = gzB64;
    }

    public boolean hasTrajectory() {
        return gzB64 != null;
    }
}
