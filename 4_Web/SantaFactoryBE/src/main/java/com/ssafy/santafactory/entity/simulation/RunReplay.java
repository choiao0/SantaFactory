package com.ssafy.santafactory.entity.simulation;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * run 하나의 주행 궤적 JSON (S15P21A106-205, 분리 -255).
 *
 * <p>{@link SimScenario} 와 1:1 이지만 연관을 걸지 않는다 — run 목록을 읽는 조회가 이 수 MB 짜리 문자열을
 * 따라 읽지 않게 하는 것이 이 테이블의 목적이라, 리플레이 API 만 id 로 직접 찾는다.
 * 맵({@code scene})은 대수와 무관하게 같으므로 견적 쪽에 한 벌만 둔다.
 */
@Entity
@Table(name = "simscenario_replays")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class RunReplay {

    @Id
    @Column(name = "scenario_id")
    private Long scenarioId;

    @Column(name = "replay_json", nullable = false)
    private String replayJson;

    public RunReplay(Long scenarioId, String replayJson) {
        this.scenarioId = scenarioId;
        this.replayJson = replayJson;
    }
}
