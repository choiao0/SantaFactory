-- run 리플레이 궤적을 별도 테이블로 (S15P21A106-255).
-- simscenarios.replay_json 은 로봇 1대당 약 0.4 MB 라 28대 run 이 12 MB 다. run 목록을 읽는 조회(상세·SSE 스냅샷·
-- 결과 도착 시 완료 판정)가 엔티티를 통째로 가져오면서 이 컬럼까지 읽어, 화면에는 KPI 몇 개만 나가는데
-- 호출마다 수십 MB 를 DB 에서 옮겼다(28대 완료 견적 약 180 MB). 리플레이 API 한 곳만 읽는 컬럼이라 따로 둔다.
CREATE TABLE simscenario_replays (
    scenario_id BIGINT PRIMARY KEY REFERENCES simscenarios (scenario_id) ON DELETE CASCADE,
    replay_json TEXT NOT NULL
);

INSERT INTO simscenario_replays (scenario_id, replay_json)
SELECT scenario_id, replay_json FROM simscenarios WHERE replay_json IS NOT NULL;

ALTER TABLE simscenarios
    DROP COLUMN replay_json;
